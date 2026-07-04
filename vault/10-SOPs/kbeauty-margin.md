---
type: sop
name: K-beauty margin formula
---

# Margin formula (what `margin_compare` computes)

Deterministic, per unit, in the product note's currency. Computed **ex-VAT**
because a VAT-registered reseller reclaims input VAT and remits output VAT, so
VAT is not part of the trading margin.

```
duty            = wholesale_unit_price × duty_pct/100
landed_cost     = wholesale_unit_price + shipping_per_unit + duty
retail_ex_vat   = retail_price / (1 + vat_pct/100)
fees            = retail_ex_vat × fees_pct/100
net_margin      = retail_ex_vat − landed_cost − fees
margin_pct      = net_margin / retail_ex_vat
markup          = retail_ex_vat / landed_cost
```

## Required inputs (no computation without them)
`wholesale_unit_price`, `shipping_per_unit`, `retail_price`.
If any is missing, the report says so and computes **nothing** — it never
substitutes a guess.

## Assumed-if-absent (flagged, not hidden)
`duty_pct`, `vat_pct`, `fees_pct` default to 0 and are listed under
"Assumed 0%" so you know the margin is provisional until you fill them in.

## Recommendation bands (on net margin %)
| Margin % | Verdict |
|----------|---------|
| ≥ 50% | strong — comfortable margin |
| 30–50% | workable — verify retail bench and shipping |
| 15–30% | thin — only at volume or higher retail |
| < 15% | reject — margin too low or negative |

## Honesty rules
- Retail is a **benchmark**, never a live market price. Verify before ordering.
- Landed cost is only as good as your shipping/duty inputs — estimate high.
- The math is deterministic; the *inputs* are your responsibility.
