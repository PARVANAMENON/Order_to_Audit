# Order-to-Audit System (Phases 1–3)

Order-to-Audit ERP prototype for a South Indian snack manufacturer in Tamil Nadu, built with Django 5, Django REST Framework, and PostgreSQL.

## Implemented Scope (Phases 1–3)

- **Phase 1 — Foundation & Masters** (`accounts`, `masters`)
  - Custom `User` model with 5 business roles (`salesman`, `admin`, `production`, `auditor`, `owner`) and server-side permission enforcement (`RoleRequiredMixin`, `@role_required`, `HasRolePermission`).
  - Table-driven `Unit` and `UnitConversion` graph conversion service (`convert_quantity`, `convert_rate`), `Item` (raw/pack/finished, HSN, GST rate, per-item variance tolerance), `Customer` (GSTIN, state), `Supplier`, `PriceList`.
  - Idempotent `seed_benchmark` management command.
- **Phase 2 — Inventory Ledger & Purchasing** (`inventory`, `purchasing`)
  - Append-only `StockLedger` with no stored balance column (`balance = SUM(StockLedger.qty)`).
  - Weighted-average cost (`get_wac`) derived purely from `StockLedger` in `Decimal`.
  - Transactional `post_purchase` inside `transaction.atomic()` with `select_for_update()`.
  - Mandatory-reason `StockAdjustment` screen and service, plus stock summary and ledger views with links to every source document.
- **Phase 3 — BOM & Production** (`bom`, `production`)
  - `BOM` and `BOMLine` definitions (e.g., Murukku 200g: 200 packets expected yield).
  - `ProductionRun` and `RunLine` with planned vs. actual consumption, good output, wastage, and damaged packaging.
  - Atomic `post_production_run` issuing raw/packaging at current WAC and receiving good FG packets.
  - Variance engine (`(actual - planned) / planned`) with 3% global default tolerance and per-item override, highlighting flagged lines and yield variances in the UI.
  - Re-posting an edited run appends `production_reversal` ledger entries before writing new movements (ledger rows are never edited or deleted).

*(Phases 4–7—sales orders, PWA, GST invoicing, dispatch, payments, overhead costing, reports, and audit log—are intentionally out of scope for this milestone.)*

## How to Run

### Using Docker Compose (recommended for clean clone)

```bash
cp .env.example .env
docker compose up --build
```

The app container automatically runs migrations, executes `python manage.py seed_benchmark`, and serves on `http://localhost:8000/`.

### Local Python / SQLite Development

```bash
pip install -r requirements.txt
python backend/manage.py migrate
python backend/manage.py seed_benchmark
python backend/manage.py runserver
```

### Verification Commands

```bash
ruff check .
pytest -q
```

## Test Logins (seeded by `seed_benchmark`)

All seeded accounts share the password **`benchmark123`**:

| Username | Role | Access Summary |
|---|---|---|
| `salesmanA` | Salesman | Assigned customer (`Retailer A`, Tamil Nadu), master catalog |
| `salesmanB` | Salesman | Assigned customer (`Distributor B`, Karnataka), master catalog |
| `admin` | Admin | Masters, purchases, stock summary/ledger, adjustments, production runs |
| `production` | Production | Purchases, stock summary/ledger, adjustments, production runs |
| `auditor` | Auditor | Strictly read-only across masters, inventory, purchases, production |
| `owner` | Owner | Read-only visibility across masters, inventory, purchases, production |

## Assumptions

1. **Carton variance flag (`9` vs `10` = `-10%`)**: Under the global 3% variance tolerance (`abs(variance) > tolerance`), using 9 cartons against a BOM plan of 10 cartons produces a `-10.00%` variance and is therefore flagged (`flagged = True`). `PACK-CARTON` uses the default 3% tolerance; if cartons are only meant to track actual packed boxes without triggering an alert, a per-item `tolerance_pct` override (e.g. `15.00%`) can be configured on `PACK-CARTON`.
2. **Pouches variance (`194` vs `200` = `-3.00%`)**: Variance flagging uses strict inequality `abs(variance) > tolerance` (`3.00% > 3.00%` is `False`), so 194 pouches used (188 good + 6 damaged) is within the 3% tolerance boundary and is not flagged.
3. **Base units & ledger rate precision**: Raw and packaging items store quantities in `Decimal(14, 3)` in their `base_unit` (`g` for flour/spice, `ml` for oil, `pcs` for pouches, `carton` for cartons, `packet` for Murukku 200g), with `display_unit` (`kg`, `L`, etc.) used for conversion at the UI/service edges. `StockLedger.unit_rate` uses `Decimal(14, 6)` so per-gram rates such as `0.043125/g` (`Rs 43.125/kg`) remain exact without rounding drift (`40,000 g * 0.043125 = Rs 1,725.00`).
4. **FG opening stock rate**: Opening balance of 50 packets of `FG-MURUKKU-200G` is seeded at rate `0.00` because Phase 2 specifies quantity without an opening unit cost; produced FG receipts from a production run carry `material_cost / actual_output` (pre-overhead) until Phase 5 overhead costing is added.
5. **Re-posting a production run**: Editing and re-posting an already-posted `ProductionRun` aggregates all prior net movements for that run and appends `production_reversal` rows in `StockLedger` before checking stock and posting the updated issue/receipt rows, preserving append-only ledger immutability.
6. **Master data API writes**: Master REST endpoints allow read access to authenticated business roles (salesmen scoped to their assigned customers) and restrict mutations to `admin`, while keeping `auditor` strictly read-only on all HTTP and DRF endpoints.
