# FactoryFlow — Order-to-Audit Manufacturing ERP

A local runnable prototype for the Centre for Digital Infrastructure, NIT Tiruchirappalli food-manufacturer order-to-audit problem. It uses only synthetic benchmark data.

## Stack and rationale
- **FastAPI + SQLite + vanilla JavaScript**: simple local setup, transparent REST endpoints and relational records that are easy to inspect during a technical interview.
- **Integer paise + Python `Decimal`** for money and quantity calculations where applicable.
- **Stock ledger as source of truth**: on-hand stock is calculated from source-linked movements, not edited as a free-standing balance.
- SQLite keeps the evaluator setup lightweight. A hosted multi-user deployment should move to PostgreSQL and use schema migrations.

## Run on Windows


```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. Keep the terminal open while using the app. If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

`run_windows.bat` is also included. The app creates `factoryflow.db` on first launch and seeds the benchmark masters.

## Demo logins
All demo passwords are `factory123`.

| Username | Role |
|---|---|
| `admin` | Factory admin |
| `salesa` | Salesman A |
| `salesb` | Salesman B |
| `production` | Production supervisor |
| `auditor` | Auditor (read-only navigation) |
| `owner` | Owner |

These are demo credentials, not production authentication. Password hashing, durable secure sessions, rate limiting and CSRF protection are not implemented; do not expose this prototype publicly with these credentials.

## Included workflows
- Role-based demo login and role-specific navigation.
- Dashboard with monthly invoiced sales trend, order pipeline, stock and top customers.
- Customer master: add retailers and distributors with state and GSTIN.
- Product master: add products with selling price, HSN, GST rate, expected batch yield and multiple BOM ingredient lines.
- Sales order: choose a customer and add multiple product/quantity lines; salesman sees own orders and customer-wise order totals.
- Admin approval checks finished-goods availability; invoice creation applies CGST/SGST for Tamil Nadu and IGST for other states; dispatch reduces finished-goods stock.
- Purchases, BOM production issue/output, planned-vs-actual variance alerts at 3%, stock ledger and weighted-average costing.
- Record payments and view invoice outstanding; add labour and utilities to a production run.
- Date-filtered report view, GST summary, collections, outstanding, sales/purchase/stock summaries and CSV/Excel/PDF exports.
- Audit events for key master and transaction operations.

## Exact NIT benchmark
Use the **Reset benchmark** action while signed in as admin/owner to restore the original benchmark master data and clear demo transactions. Then follow the scenario in the problem statement.

For a repeatable local run of the complete benchmark, from the project root execute:

```powershell
python scripts/seed_benchmark.py
```

**Warning:** this script resets the local demo database before running the benchmark. It uses the FastAPI test client to execute the purchase, production, Retailer A order/invoice/dispatch, Distributor B shortage check, ₹4,000 payment and overhead entries.

Verified benchmark outputs from the script:

| Check | Result |
|---|---:|
| Flour closing | 120 kg |
| Cooking oil closing | 19.5 L |
| Spice mix closing | 3.8 kg |
| Pouch closing | 306 pieces |
| Carton closing | 21 pieces |
| Finished goods after production | 238 packets |
| Finished goods after Retailer A dispatch | 88 packets |
| Yield variance | -6% (flagged) |
| Oil variance | +5% (flagged) |
| Retailer A taxable value | ₹7,500.00 |
| CGST + SGST | ₹187.50 + ₹187.50 |
| Retailer A invoice total | ₹7,875.00 |
| Retailer A outstanding after ₹4,000 payment | ₹3,875.00 |
| Distributor B approval | Blocked: 32-packet shortage |

Pouch consumption is 188 good pouches + 6 damaged pouches = 194; therefore 500 − 194 = 306. Carton issue is the stated 9 pieces. Flour valuation after the purchase uses weighted average: `(100 × 42 + 60 × 45) / 160 = ₹43.125/kg`. The costing view adds actual material cost and run labour/utilities, then divides by good output.

## Tests
Run the included benchmark arithmetic tests:

```powershell
python -m unittest discover -s tests -v
```

The benchmark runner is an end-to-end API walkthrough; it prints the resulting balances and shortage response.

## Design note
See [DESIGN_NOTE.md](DESIGN_NOTE.md) for entities, stock ledger, BOM variance, costing and GST assumptions. `ENHANCEMENTS.md` lists the latest changes.

## Requirement coverage and known gaps
This is a **working prototype**, not a claim that every optional or statutory requirement is complete.

- **Implemented core:** role-based demo access, customer/product/BOM masters, multi-line order entry, approval/stock check, illustrative GST PDF invoice, dispatch, purchase receipt, production run, stock movement ledger, variance, weighted-average costing, payment/outstanding, basic audit events and report exports.
- **Partially implemented:** monthly report filtering applies to invoice/purchase/production/payment summary data, but the downloadable exports are summary-oriented rather than a complete auditor pack. GST output is a prototype summary, not a certified GSTR-1/3B reconciliation. Invoice PDF is illustrative.
- **Not implemented:** offline-first order sync, unit conversion engine, batch/expiry and FEFO, partial dispatch/returns, credit notes and immutable posted-invoice correction, comprehensive edit audit trail, supplier master, full ageing buckets, GPS route logs, Tally export and production deployment hardening.
- **Important model limitation:** production entry supports the BOM lines and benchmark packaging fields; the prototype still uses benchmark-specific pouch/carton handling and does not yet provide a general packaging-waste/unit-conversion rules engine for arbitrary recipes.
- **Security limitation:** demo passwords are stored in the prototype database as plain text and sessions are in-memory. This must be replaced before deployment.

The system should be presented as a prototype whose benchmark path is reproducible, with the gaps above stated openly in the interview.
