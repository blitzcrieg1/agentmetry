---
type: product
name: ""                    # display name
sku: ""
inci: ""                   # key actives / INCI for EU cosmetic copy
# --- margin inputs (all EUR unless currency says otherwise) ---
currency: EUR
wholesale_unit_price:      # REQUIRED — per-unit from a real supplier quote
moq:                       # units per order (context, not used in per-unit margin)
shipping_per_unit:         # REQUIRED — allocate freight/handling per unit
duty_pct: 0                # import duty % of wholesale (0 if intra-EU)
vat_pct: 24                # Greece standard VAT; margin is computed ex-VAT
fees_pct: 3                # platform + payment fees % of retail
retail_price:              # REQUIRED — operator-verified price or a clearly-marked bench
retail_source: ""          # URL if the retail figure came from research (unverified)
---

# Product — <name>

## Positioning
(who it's for, why it sells in Greece/EU)

## Sourcing
- Supplier: [[10-Suppliers/<supplier>]]
- COA / CPNP status:

## Notes
Margin is computed deterministically by the `margin_compare` skill from the
frontmatter above. Leave a required field blank and the report will tell you
exactly what's missing — it never guesses a price.
