"""margin — deterministic landed-cost / net-margin MCP driver.

No LLM, no scraping, no guessing: reads a product note's structured frontmatter
and computes margin arithmetically. Missing hard inputs are reported as missing,
never invented. Local and secret-free — ships enabled.

Frontmatter it reads (see vault/10-Products/_template-product.md):

    wholesale_unit_price: 3.80     # required
    shipping_per_unit: 0.60        # required (landed cost is meaningless without it)
    retail_price: 14.90            # required (operator-verified or clearly a bench)
    currency: EUR
    duty_pct: 0                    # optional; absent -> assumed 0%, flagged
    vat_pct: 24                    # optional; absent -> assumed 0%, flagged
    fees_pct: 3                    # optional; absent -> assumed 0%, flagged
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml
from mcp.server.fastmcp import FastMCP

server = FastMCP("margin")

VAULT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd() / "vault"

_REQUIRED = ("wholesale_unit_price", "shipping_per_unit", "retail_price")
_ASSUMED_ZERO = ("duty_pct", "vat_pct", "fees_pct")

# Deterministic recommendation bands on net margin % (documented in the SOP).
_BANDS = (
    (0.50, "strong — comfortable margin"),
    (0.30, "workable — verify retail bench and shipping"),
    (0.15, "thin — only at volume or higher retail"),
    (float("-inf"), "reject — margin too low or negative"),
)


def _safe(rel: str) -> Path:
    path = (VAULT / rel).resolve()
    if path != VAULT and VAULT not in path.parents:
        raise ValueError(f"Path escapes vault: {rel}")
    return path


def parse_product_note(text: str) -> dict[str, Any]:
    """Extract the YAML frontmatter block as a dict (empty if none)."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return {}
    data = yaml.safe_load(match.group(1))
    return data if isinstance(data, dict) else {}


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def compute_margin(fields: dict[str, Any]) -> dict[str, Any]:
    """Pure deterministic margin math. Reports missing inputs; never guesses.

    Net margin is computed ex-VAT (a VAT-registered reseller reclaims input VAT
    and remits output VAT), so retail is divided down by vat_pct before margin.
    """
    missing = [k for k in _REQUIRED if _num(fields.get(k)) is None]
    assumed = [k for k in _ASSUMED_ZERO if _num(fields.get(k)) is None]

    result: dict[str, Any] = {
        "currency": fields.get("currency", "EUR"),
        "missing": missing,
        "assumed_zero": assumed,
        "computable": not missing,
    }
    if missing:
        return result

    wholesale = _num(fields["wholesale_unit_price"])
    shipping = _num(fields["shipping_per_unit"])
    retail = _num(fields["retail_price"])
    duty_pct = _num(fields.get("duty_pct")) or 0.0
    vat_pct = _num(fields.get("vat_pct")) or 0.0
    fees_pct = _num(fields.get("fees_pct")) or 0.0

    duty = wholesale * duty_pct / 100.0
    landed = wholesale + shipping + duty
    retail_ex_vat = retail / (1.0 + vat_pct / 100.0)
    fees = retail_ex_vat * fees_pct / 100.0
    net = retail_ex_vat - landed - fees
    margin_pct = net / retail_ex_vat if retail_ex_vat else 0.0
    markup_x = retail_ex_vat / landed if landed else 0.0

    recommendation = next(label for floor, label in _BANDS if margin_pct >= floor)

    result.update(
        {
            "landed_unit_cost": round(landed, 4),
            "retail_ex_vat": round(retail_ex_vat, 4),
            "fees_per_unit": round(fees, 4),
            "net_margin_per_unit": round(net, 4),
            "margin_pct": round(margin_pct * 100, 1),
            "markup_x": round(markup_x, 2),
            "recommendation": recommendation,
        }
    )
    return result


def render_report(name: str, r: dict[str, Any]) -> str:
    cur = r["currency"]
    lines = [f"## Margin — {name}"]
    if not r["computable"]:
        lines.append(
            "\n**Cannot compute net margin.** Missing required inputs: "
            + ", ".join(f"`{m}`" for m in r["missing"])
            + "\n\nAdd them to the product note frontmatter and re-run — "
            "no values were assumed."
        )
        return "\n".join(lines)

    lines += [
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Landed unit cost | {r['landed_unit_cost']:.2f} {cur} |",
        f"| Retail (ex-VAT) | {r['retail_ex_vat']:.2f} {cur} |",
        f"| Fees / unit | {r['fees_per_unit']:.2f} {cur} |",
        f"| **Net margin / unit** | **{r['net_margin_per_unit']:.2f} {cur}** |",
        f"| Margin % | {r['margin_pct']:.1f}% |",
        f"| Markup | {r['markup_x']:.2f}× |",
        "",
        f"**Recommendation:** {r['recommendation']}",
    ]
    if r["assumed_zero"]:
        lines.append(
            "\n_Assumed 0% (not stated in note): "
            + ", ".join(f"`{a}`" for a in r["assumed_zero"])
            + " — confirm before trusting the margin._"
        )
    lines.append(
        "\n_Retail is a benchmark from the note, not a live market price. "
        "Verify before committing to an order._"
    )
    return "\n".join(lines)


@server.tool()
def compute_from_note(path: str) -> str:
    """Compute landed cost + net margin from a product note's frontmatter."""
    target = _safe(path)
    if not target.is_file():
        raise FileNotFoundError(f"No such product note: {path}")
    fields = parse_product_note(target.read_text(encoding="utf-8"))
    if not fields:
        return f"## Margin — {path}\n\nNo frontmatter found. Use the product template."
    name = fields.get("name") or Path(path).stem
    return render_report(str(name), compute_margin(fields))


if __name__ == "__main__":
    server.run()
