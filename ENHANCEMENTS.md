# Enhancement Notes

## Latest update — NIT task workflow improvements
- Added customer creation with customer type, state and GSTIN.
- Added product creation with SKU, pack size, price, HSN, GST rate, expected batch yield and multiple BOM ingredient lines.
- Added multi-product sales orders with multiple quantity lines.
- Added customer-wise order/packet/taxable-value summary for the logged-in salesman.
- Added product-specific expected batch output and BOM listing across all products.
- Added date filters to the report API and report screen; added collections and outstanding totals to the report summary.
- Added a repeatable benchmark runner (`scripts/seed_benchmark.py`) and arithmetic regression tests (`tests/test_math.py`).
- Verified the end-to-end benchmark API path: ₹7,875 Retailer A invoice, ₹3,875 outstanding, 88 finished packets after dispatch, and Distributor B approval blocked for a 32-packet shortage.

## Existing application features
- Dashboard sales trend, order pipeline, top customers and stock snapshot.
- Role-based navigation, order approval, GST invoice PDF, dispatch and payment collection.
- Purchases, BOM-based production, stock ledger, variance alerts and weighted-average costing.
- CSV, Excel and PDF report downloads.

## Remaining work (do not represent these as completed)
- Offline order queue and synchronization.
- General unit conversion, batch/expiry tracking and FEFO dispatch.
- Partial dispatch, returns, credit notes and immutable posted invoices.
- Complete auditor export pack, statutory GST reconciliation and full receivables ageing.
- Password hashing, secure persistent sessions, CSRF/rate-limit protections and production database migration.
