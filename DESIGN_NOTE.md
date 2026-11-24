# FactoryFlow — Design Note

## 1. Architecture
Browser UI → FastAPI REST API → SQLite relational database. SQLite makes the local demo reproducible without external services. For deployment, use PostgreSQL, schema migrations and managed secrets.

## 2. Core entities
- `users`: demo username and role.
- `customers`: retailer/distributor, state and GSTIN.
- `products`: SKU, pack size, selling price in paise, HSN, GST rate and expected batch output.
- `materials`: raw/packaging item, unit, opening quantity and valuation rate.
- `bom_lines`: product, material and standard quantity per batch.
- `purchases`: supplier, item, quantity and unit rate.
- `production_runs` / `production_actuals`: product, batch count, expected/good output, actual and planned consumption, packaging waste and overheads.
- `stock_movements`: material/product, quantity delta, unit, source type/id and timestamp.
- `orders` / `order_lines`, `invoices`, `payments`, `audit_events`.

## 3. Stock computation and traceability
On-hand quantity is the sum of stock movement deltas for an item. Opening balances, purchases, production issues, production output and dispatch each create a movement with a source type and source ID. The ledger, rather than a user-editable balance, is the source of truth. Mutating operations use SQLite transactions.

## 4. BOM and variance
For `n` batches, planned material consumption is `BOM quantity × n`. Material variance is `(actual − planned) / planned × 100`. Expected output is the product's configured expected batch yield multiplied by batch count. Yield variance is `(good output − expected output) / expected output × 100`. The UI flags absolute variance above 3%.

The benchmark's packaging handling is specific: actual pouch issue is good output plus damaged pouches; carton issue is the entered actual carton count. A generalized packaging conversion and wastage rules engine remains future work.

## 5. Costing
Raw-material valuation uses weighted average, including opening stock and recorded purchases. For flour after the benchmark purchase: `(100×42 + 60×45)/160 = ₹43.125/kg`. The run cost sums actual material consumption at weighted-average rates plus labour and utilities. Cost per good packet is run cost divided by actual good output. This is an approximation; freight, input tax credit, returns and broader overhead allocation are not modeled.

## 6. Tax and money
Money values are stored as integer paise and calculations use decimal rounding. The benchmark uses 5% GST. Tamil Nadu supply splits tax into CGST 2.5% and SGST 2.5%; Karnataka supply uses IGST 5%. Invoice PDF and GST summary are illustrative and need statutory review before real use.

## 7. Assumptions and limitations
- No pouch purchase occurs: 500 − 188 good pouches − 6 damaged pouches = 306.
- Cartons are issued as 9 actual pieces, as stated in the scenario.
- The app blocks approval/dispatch when finished goods are insufficient; negative stock is not allowed.
- Partial dispatch, returns, credit notes, immutable posted invoices, generalized unit conversion, batch/expiry and FEFO are not implemented.
- Demo credentials are not securely hashed and session tokens are in-memory. The prototype must be hardened before public deployment.
