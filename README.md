DEMO VIDEO -->https://drive.google.com/file/d/1U6paqgxMVbpG3PNv-Me2hOphy_1sYfn2/view?usp=sharing

# Order-to-Audit System (Phases 1–8)

Order-to-Audit ERP prototype for a South Indian snack manufacturer in Tamil Nadu, built with Django 5, Django REST Framework, and PostgreSQL.

## Implemented Scope (Phases 1–8)

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
- **Phase 4 — Sales Orders & Salesman PWA** (`sales`)
  - `Order`/`OrderLine` lifecycle (`draft → submitted → approved/rejected → invoiced`) with mandatory rejection reasons and admin quantity adjustments on approval.
  - Stock-coverage warnings at approval time; salesmen are scoped to their assigned customers.
  - Idempotent order submission API (`/api/orders/`) keyed by `idempotency_key` so offline retries never duplicate orders.
  - Installable field-capture PWA at `/sales/pwa/` with manifest and service worker; orders taken offline are queued in `localStorage` and replayed automatically.
- **Phase 5 — GST Invoicing, Dispatch, Payments & Overhead Costing** (`sales`, `payments`, `costing`)
  - Gapless FY invoice numbering (`2026-27/0001`) and GST engine: 5% intra-state split into CGST/SGST, IGST for inter-state supply.
  - ReportLab tax-invoice PDF, dispatch posting to the stock ledger for finished goods (idempotent), and credit notes that reverse revenue/tax and optionally stock.
  - Customer payments with manual or automatic FIFO allocation, outstanding computation, and 0–30/31–60/61–90/90+ ageing buckets.
  - Run-level overhead entries (labour, power, gas, other) feeding cost-per-packet, selling price, margin and margin %.
- **Phase 6 — Reports & Dashboard** (`reports`)
  - Owner dashboard (today's orders, pending approvals, flagged runs, low stock, total dues).
  - Sales register (CSV export), GST summary, purchase register, production variance, item stock ledger, and outstanding dues.
- **Phase 7 — Audit Trail** (`audit`)
  - Append-only `AuditLog` recording every significant write (orders, invoices, dispatch, credit notes, payments, overheads, purchases, production, adjustments) with actor, before/after JSON and notes.
  - Filterable, read-only audit screen (`/audit/`); the model is immutable in Django admin.
- **Phase 8 — Production Hardening & Deployment** (`config`, `core`)
  - Environment-driven settings: `DATABASE_URL` (or `POSTGRES_*`), optional Redis cache, `CSRF_TRUSTED_ORIGINS`, secure cookies, HSTS/SSL redirect and reverse-proxy header toggles; production refuses to start with the development secret key.
  - Gunicorn + WhiteNoise in a multi-stage, non-root Docker image; container entrypoint runs migrations and `collectstatic` before serving.
  - `/healthz` liveness/readiness probe checking the database, wired into Docker and Compose health checks.
  - `backup_db` management command (timestamped `pg_dump` custom-format backups for PostgreSQL, file copy for SQLite, retention pruning) and optional Sentry error monitoring via `SENTRY_DSN`.
  - GitHub Actions CI running Ruff, the missing-migrations check, the test suite, and the production image build.

## How to Run

### Using Docker Compose (recommended for clean clone)

```bash
cp .env.example .env
docker compose up --build
```

The app container runs migrations and `collectstatic`, seeds the benchmark data plus demo documents (`SEED_DEMO_DATA=1` runs `seed_benchmark --demo`), then serves through Gunicorn on `http://localhost:8000/`. PostgreSQL and Redis start alongside it, and the app is only reported healthy once `/healthz` returns 200.

### Local Python / SQLite Development

```bash
pip install -r requirements.txt
python backend/manage.py migrate
python backend/manage.py seed_benchmark
# Optional: add a demo purchase, production run, orders, invoice, dispatch and payment
python backend/manage.py seed_benchmark --demo
python backend/manage.py runserver
```

### Verification Commands

```bash
ruff check .
pytest -q
python backend/manage.py makemigrations --check --dry-run
python backend/manage.py check
```

## Production Deployment

Set `DJANGO_DEBUG=0`, a unique `DJANGO_SECRET_KEY`, and the real host names before starting the stack. In production, leave `SEED_DEMO_DATA=0` so demo accounts and data are not created.

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Required when `DJANGO_DEBUG=0`; startup fails with the development default. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames; add the public domain. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Comma-separated origins such as `https://erp.example.com`. |
| `DATABASE_URL` | `postgres://user:pass@host:5432/dbname`; overrides the `POSTGRES_*` variables. |
| `REDIS_URL` | Enables the Redis cache backend; omitted, Django uses in-memory caching. |
| `DJANGO_TRUST_PROXY_HEADERS` | `1` behind a TLS-terminating proxy so Django sees HTTPS. |
| `DJANGO_SECURE_SSL_REDIRECT` / `DJANGO_SECURE_COOKIES` / `DJANGO_SECURE_HSTS_SECONDS` | Redirect to HTTPS, secure cookies and HSTS; enable once TLS is confirmed. |
| `SENTRY_DSN` | Sends exceptions to any Sentry-compatible endpoint; requires `sentry-sdk`. |
| `DJANGO_LOG_LEVEL` | Root log level (default `INFO` in production). |

Operational commands:

```bash
# Timestamped backup, keeping the 14 most recent files (default)
python backend/manage.py backup_db
python backend/manage.py backup_db --output-dir /var/backups/ota --keep 30

# Health probe
curl -fsS http://localhost:8000/healthz
```

The container writes backups to `/app/backups` (the `backups` Compose volume); schedule `backup_db` from cron or a platform scheduler, and copy the files off the host. The production image build is validated by CI, which also runs lint, the migrations check and tests on every pull request.

## Test Logins (seeded by `seed_benchmark`)

All seeded accounts share the password **`benchmark123`**:

| Username | Role | Access Summary |
|---|---|---|
| `salesmanA` | Salesman | Assigned customer (`Retailer A`, Tamil Nadu), orders, own invoices, field-capture PWA |
| `salesmanB` | Salesman | Assigned customer (`Distributor B`, Karnataka), orders, own invoices, field-capture PWA |
| `admin` | Admin | Full masters, purchasing, production, sales, invoicing, dispatch, payments, reports, audit |
| `production` | Production | Purchases, stock, adjustments, production runs, run costing, production reports, audit |
| `auditor` | Auditor | Strictly read-only across masters, inventory, purchases, production, sales, payments, reports, audit |
| `owner` | Owner | Read-only visibility across masters, inventory, production, sales, payments, reports, audit |

## Assumptions

1. **Carton variance flag (`9` vs `10` = `-10%`)**: Under the global 3% variance tolerance (`abs(variance) > tolerance`), using 9 cartons against a BOM plan of 10 cartons produces a `-10.00%` variance and is therefore flagged (`flagged = True`). `PACK-CARTON` uses the default 3% tolerance; if cartons are only meant to track actual packed boxes without triggering an alert, a per-item `tolerance_pct` override (e.g. `15.00%`) can be configured on `PACK-CARTON`.
2. **Pouches variance (`194` vs `200` = `-3.00%`)**: Variance flagging uses strict inequality `abs(variance) > tolerance` (`3.00% > 3.00%` is `False`), so 194 pouches used (188 good + 6 damaged) is within the 3% tolerance boundary and is not flagged.
3. **Base units & ledger rate precision**: Raw and packaging items store quantities in `Decimal(14, 3)` in their `base_unit` (`g` for flour/spice, `ml` for oil, `pcs` for pouches, `carton` for cartons, `packet` for Murukku 200g), with `display_unit` (`kg`, `L`, etc.) used for conversion at the UI/service edges. `StockLedger.unit_rate` uses `Decimal(14, 6)` so per-gram rates such as `0.043125/g` (`Rs 43.125/kg`) remain exact without rounding drift (`40,000 g * 0.043125 = Rs 1,725.00`).
4. **FG opening stock rate**: Opening balance of 50 packets of `FG-MURUKKU-200G` is seeded at rate `0.00` because Phase 2 specifies quantity without an opening unit cost; produced FG receipts from a production run carry `material_cost / actual_output` (pre-overhead) until Phase 5 overhead costing is added.
5. **Re-posting a production run**: Editing and re-posting an already-posted `ProductionRun` aggregates all prior net movements for that run and appends `production_reversal` rows in `StockLedger` before checking stock and posting the updated issue/receipt rows, preserving append-only ledger immutability.
6. **Master data API writes**: Master REST endpoints allow read access to authenticated business roles (salesmen scoped to their assigned customers) and restrict mutations to `admin`, while keeping `auditor` strictly read-only on all HTTP and DRF endpoints.
7. **GST split**: A 5% GST rate is applied as CGST 2.5% + SGST 2.5% when the customer's state is Tamil Nadu, and as IGST 5% otherwise; tax is rounded half-up at the invoice-line and invoice-total level.
8. **Invoice numbering**: FY numbers are generated as `YYYY-YY/NNNN` (April–March) inside the invoicing transaction. Numbers are gapless for the normal create-only flow; rows must not be deleted.
9. **Dispatch idempotency**: Posting dispatch against an invoice that already has a dispatched/partial dispatch returns the existing document instead of deducting stock twice.
10. **Payment allocation**: When no explicit allocation is supplied, payments are applied FIFO to the customer's oldest active invoices; overpayments leave an unallocated remainder, and allocations to another customer's or a cancelled invoice are rejected.
11. **Audit immutability**: `AuditLog` rows are written in the same transaction as the action they describe and are never updated or deleted (Django admin blocks add/change/delete).
12. **Offline PWA**: The field-capture shell caches only `/sales/pwa/`; queued orders are stored in browser `localStorage` and replayed through the idempotent API. A device must have signed in online at least once for its session cookie to remain valid.
13. **Production settings**: Security toggles (secure cookies, SSL redirect, HSTS, proxy headers) are opt-in via environment variables because the same settings module serves local HTTP development. Only `SECRET_KEY` is mandatory in production.
14. **Backups**: `backup_db` uses `pg_dump` (PostgreSQL client tools must be installed) or a file copy for SQLite. It produces application-consistent dumps but does not upload them; off-host transfer and restore drills remain an operator responsibility.
