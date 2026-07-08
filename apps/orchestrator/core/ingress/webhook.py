"""Universal webhook ingress — JSON payloads to vault notes + skill runs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import yaml

_MAX_FRONTMATTER_SCALAR_LEN = 500
_MAX_JSON_BODY_CHARS = 50_000


def _slug_source(source: str) -> str:
    slug = re.sub(r"[^\w-]", "-", source.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "webhook"


def _scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and len(value) > _MAX_FRONTMATTER_SCALAR_LEN:
            return value[:_MAX_FRONTMATTER_SCALAR_LEN] + "…"
        return value
    return None


def payload_to_markdown(
    payload: dict[str, Any],
    *,
    source: str,
    target_skill: str,
) -> str:
    """Convert arbitrary webhook JSON into a vault note with frontmatter + body."""
    received = datetime.now(timezone.utc).isoformat()
    frontmatter: dict[str, Any] = {
        "type": "ingress",
        "source": source,
        "target_skill": target_skill,
        "received": received,
    }

    complex_fields: dict[str, Any] = {}
    table_rows: list[tuple[str, str]] = []

    for key, value in payload.items():
        scalar = _scalar(value)
        if scalar is not None:
            frontmatter[str(key)] = scalar
            table_rows.append((str(key), str(scalar)))
        else:
            complex_fields[str(key)] = value

    yaml_block = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    lines = [
        "---",
        yaml_block.rstrip(),
        "---",
        "",
        "# Webhook Event",
        "",
        f"Inbound from **{source}** → skill `{target_skill}`.",
        "",
    ]

    if table_rows:
        lines.extend(["## Fields", "", "| Field | Value |", "| --- | --- |"])
        for field, val in table_rows:
            escaped = val.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {field} | {escaped} |")
        lines.append("")

    for key, value in complex_fields.items():
        blob = json.dumps(value, indent=2, ensure_ascii=False)
        if len(blob) > _MAX_JSON_BODY_CHARS:
            blob = blob[:_MAX_JSON_BODY_CHARS] + "\n…"
        lines.extend([f"## {key}", "", "```json", blob, "```", ""])

    return "\n".join(lines).rstrip() + "\n"


def ingress_filename(source: str, *, now: datetime | None = None) -> str:
    """Vault-relative path under 00-Inbox/."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d-%H%M%S")
    return f"00-Inbox/ingress-{_slug_source(source)}-{stamp}.md"
