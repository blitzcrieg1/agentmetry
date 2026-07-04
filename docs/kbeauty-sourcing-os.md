# K-beauty Sourcing OS (v1)

A research ledger + deterministic margin calculator for a Greece/EU K-beauty
e-shop. **It is not a scraper.** It finds leads and does the math; you verify
the numbers before money moves.

## What it can and can't do

| Want | Reality |
|------|---------|
| Trend + wholesaler discovery | ✅ via `search.web` (cited URLs) |
| Retail price signals | ⚠️ search snippets only, **unverified**, cited |
| Landed cost + net margin | ✅ deterministic, from inputs you supply |
| Live retail/marketplace prices | ❌ no scraping, no feeds |
| "Real profit" with no inputs | ❌ needs your shipping/duty/VAT/fees |
| Auto-order / send email | ❌ out of scope (drafts only, elsewhere) |

## Setup

1. **Enable search** (for trend research): `docs/search-driver-live.md`.
   The `margin` driver is local and ships **enabled** — no key needed.
2. `scripts\blackbox.bat start`.

## Workflow

### 1. Research a category
Dashboard → Armory → **K-beauty Trend Research**, input e.g.
`korean snail mucin Greece`. Approve the brief; it archives trend signals,
wholesaler leads, and unverified retail benchmarks — all with URLs.

### 2. Capture a product
Copy `10-Products/_template-product.md`. Fill the margin inputs from a **real
supplier quote** (paste it through `supplier_intake` first) and a retail bench
you've checked. A blank field means "missing", never "zero".

Required for a margin: `wholesale_unit_price`, `shipping_per_unit`,
`retail_price`. Optional (assumed 0% and flagged if absent): `duty_pct`,
`vat_pct`, `fees_pct`.

### 3. Compute margin
Armory → **Margin Compare**, input the product note path
(e.g. `10-Products/sample-snail-essence.md`). The `margin` tool computes landed
cost, net margin %, markup, and a recommendation — deterministically, per
`10-SOPs/kbeauty-margin.md`. Missing inputs are listed; nothing is guessed.

### Try it now (shipped sample)
`Margin Compare` on `10-Products/sample-snail-essence.md` →
~60% margin, "strong". Blank a required field to see the missing-data report.

## Honesty contract
- Retail figures from research are **benchmarks**, not live prices — verify.
- The arithmetic is deterministic and unit-tested; the **inputs are yours**.
- Suppliers found via search are **leads** — confirm MOQ/COA/incoterms directly
  before ordering (`10-Suppliers/_template-supplier.md`, `verified: true`).
