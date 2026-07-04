"""Deterministic margin math — the arithmetic must be exact and never guess."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SERVER = Path(__file__).resolve().parents[1] / "tools" / "margin_server.py"

spec = importlib.util.spec_from_file_location("margin_server", _SERVER)
margin_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(margin_server)

compute_margin = margin_server.compute_margin
parse_product_note = margin_server.parse_product_note
render_report = margin_server.render_report


def test_full_computation_is_exact():
    r = compute_margin({
        "wholesale_unit_price": 3.80,
        "shipping_per_unit": 0.60,
        "duty_pct": 0,
        "vat_pct": 24,
        "fees_pct": 3,
        "retail_price": 14.90,
    })
    assert r["computable"] is True
    assert r["landed_unit_cost"] == pytest.approx(4.40)          # 3.80 + 0.60 + 0
    ex_vat = 14.90 / 1.24
    assert r["retail_ex_vat"] == pytest.approx(ex_vat, abs=1e-3)  # 12.0161...
    net = ex_vat - 4.40 - ex_vat * 0.03
    assert r["net_margin_per_unit"] == pytest.approx(net, abs=1e-3)
    assert r["margin_pct"] == pytest.approx(net / ex_vat * 100, abs=0.1)
    assert r["margin_pct"] == pytest.approx(60.4, abs=0.2)
    assert r["recommendation"].startswith("strong")             # ~60% margin


def test_duty_enters_landed_cost():
    r = compute_margin({
        "wholesale_unit_price": 10.0, "shipping_per_unit": 0.0,
        "duty_pct": 10, "vat_pct": 0, "fees_pct": 0, "retail_price": 20.0,
    })
    assert r["landed_unit_cost"] == pytest.approx(11.0)          # 10 + 0 + 1
    assert r["retail_ex_vat"] == pytest.approx(20.0)             # vat 0
    assert r["net_margin_per_unit"] == pytest.approx(9.0)


def test_missing_required_blocks_computation():
    r = compute_margin({"wholesale_unit_price": 3.8, "vat_pct": 24})
    assert r["computable"] is False
    assert set(r["missing"]) == {"shipping_per_unit", "retail_price"}
    assert "net_margin_per_unit" not in r          # nothing invented


def test_absent_optionals_are_assumed_zero_and_flagged():
    r = compute_margin({
        "wholesale_unit_price": 5.0, "shipping_per_unit": 1.0, "retail_price": 10.0,
    })
    assert r["computable"] is True
    assert set(r["assumed_zero"]) == {"duty_pct", "vat_pct", "fees_pct"}
    assert r["landed_unit_cost"] == pytest.approx(6.0)
    assert r["net_margin_per_unit"] == pytest.approx(4.0)        # vat/fees/duty = 0


def test_strings_are_not_treated_as_numbers():
    # A blank template field parses as None/"" — must count as missing, not 0.
    r = compute_margin({
        "wholesale_unit_price": "", "shipping_per_unit": None, "retail_price": 10.0,
    })
    assert r["computable"] is False
    assert "wholesale_unit_price" in r["missing"]
    assert "shipping_per_unit" in r["missing"]


def test_recommendation_bands():
    strong = compute_margin({"wholesale_unit_price": 1.0, "shipping_per_unit": 0.0,
                             "retail_price": 10.0})
    assert strong["recommendation"].startswith("strong")
    reject = compute_margin({"wholesale_unit_price": 9.5, "shipping_per_unit": 0.5,
                             "retail_price": 10.0})
    assert reject["recommendation"].startswith("reject")


def test_parse_frontmatter_roundtrip():
    note = "---\nname: X\nwholesale_unit_price: 3.8\n---\n\n# body\n"
    fields = parse_product_note(note)
    assert fields["wholesale_unit_price"] == 3.8
    assert parse_product_note("no frontmatter here") == {}


def test_render_missing_report_names_fields():
    out = render_report("Widget", compute_margin({"wholesale_unit_price": 1.0}))
    assert "Cannot compute" in out
    assert "shipping_per_unit" in out and "retail_price" in out


def test_render_full_report_has_table_and_recommendation():
    out = render_report("Essence", compute_margin({
        "wholesale_unit_price": 3.80, "shipping_per_unit": 0.60,
        "vat_pct": 24, "fees_pct": 3, "retail_price": 14.90,
    }))
    assert "Net margin / unit" in out
    assert "Recommendation:" in out
    assert "benchmark" in out.lower()          # honesty caveat present


def test_sample_product_note_computes():
    """The shipped demo note must produce a real margin (default_input target)."""
    vault = Path(__file__).resolve().parents[3] / "vault"
    note = (vault / "10-Products" / "sample-snail-essence.md").read_text(encoding="utf-8")
    r = compute_margin(parse_product_note(note))
    assert r["computable"] is True
    assert r["net_margin_per_unit"] > 0
