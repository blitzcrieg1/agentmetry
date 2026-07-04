---
type: sop
name: K-beauty sourcing workflow
---

# Sourcing workflow (research → verify → margin)

BLACKBOX is a **research ledger + calculator**, not a scraper. It finds leads
and does the math; you verify the numbers before money moves.

## 1. Trend + leads (skill: `kbeauty_trend_research`)
Run with a product/category query (e.g. "korean snail mucin Greece").
Requires the **search driver enabled** (`docs/search-driver-live.md`).
Output → `30-Archive/`: trend signals, wholesaler leads, and **unverified**
retail price signals — every claim carries a URL. Approve before it finalizes.

## 2. Capture a product (template: `10-Products/_template-product.md`)
Create a product note. Fill margin inputs from a **real supplier quote**
(paste it through `supplier_intake` first) and a **verified or clearly-marked**
retail bench. Blank = missing, not zero.

## 3. Verify the supplier (template: `10-Suppliers/_template-supplier.md`)
Confirm MOQ, COA/CPNP, incoterms **directly** — search leads are starting
points, not facts. Set `verified: true` only after you've checked.

## 4. Margin (skill: `margin_compare`)
Run on the product note path. The `margin` tool computes landed cost and net
margin deterministically (see `kbeauty-margin.md`) and lists anything missing.
No LLM arithmetic; no invented prices.

## What this does NOT do
- No live retail scraping or marketplace feeds (search snippets only, cited).
- No auto-ordering, no payments, no sending email (drafts only, elsewhere).
- No "real profit" without your shipping/duty/VAT/fees inputs.
