# CLAUDE.md

Self-hosted household finance app (working name `finance-app`, final name not decided).
Inspired by the feature set of Finanzguru, but with its own name, design and code.
Deployed with Docker Compose on a Proxmox VM, reachable through Cloudflare Tunnel + Access.

## Layout

- `backend/` – Python 3.13, FastAPI, SQLAlchemy 2 (sync), Alembic, Procrastinate (job queue in Postgres)
  - `app/api/` routers, `app/models/` ORM models, `app/security/` crypto, TOTP, Cloudflare Access
  - `app/sessions.py` server-side sessions (cookie `fa_session`), `app/deps.py` auth dependencies
  - `app/finance/` ledger logic: `access.py` (visibility of accounts, transactions, contracts and savings goals, the only place that decides it), rules, transfers, dedupe, reporting, importer, contracts (detection and payment matching), budgets, available-to-spend, forecast, savings goals, export (CSV/XLSX), year reports, notifications
  - `app/importing/` pure CSV parsing (presets, header auto-mapping), no database access
  - `app/banking/` Enable Banking client, response mapping and the sync that feeds new rows through the same pipeline as a CSV import
  - `app/worker.py` background tasks, `app/cli.py` admin commands
- `frontend/` – React 19, Vite, TypeScript, TanStack Router + Query, Tailwind CSS 4, shadcn-style components
  - `src/api/schema.d.ts` is generated from the backend OpenAPI schema; never edit by hand
- `deploy/backup/` – pg_dump + restic image
- `compose.yaml` production stack, `compose.dev.yaml` local database

## Commands

Backend (in `backend/`):
- `uv sync` · `uv run pytest` (needs Docker for testcontainers) · `uv run ruff format . && uv run ruff check .` · `uv run mypy app tests`
- Dev server: `docker compose -f ../compose.dev.yaml up -d`, then with `FA_DB_PASSWORD=devpass FA_ENCRYPTION_KEY=<key> FA_COOKIE_SECURE=false`: `uv run alembic upgrade head && uv run uvicorn app.main:app --reload`
- New migration: `uv run alembic revision --autogenerate -m "..."`, then review the file

Frontend (in `frontend/`):
- `pnpm install` · `pnpm dev` (proxies `/api` to :8000) · `pnpm check` · `pnpm typecheck` · `pnpm test` · `pnpm build`

After changing API routes or schemas, regenerate the client types (CI fails otherwise):
`cd backend && FA_ENCRYPTION_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= uv run python -m app.cli export-openapi > ../frontend/src/api/openapi.json && cd ../frontend && pnpm api:types`

## Conventions

- Money is stored as integer cents (`bigint`), never float. Display with `Intl.NumberFormat("de-DE")`.
- Dates in the UI: `TT.MM.JJJJ` via `src/lib/format.ts`. UI text is German, code and comments English.
- API error `detail` strings are English; the frontend maps status codes to German messages.
- Every household-scoped query filters by the caller's household (`CurrentMember`). Add an isolation test for new endpoints.
- Private accounts are visible only to their owner: go through `app.finance.access` for accounts, transactions, contracts and savings goals; hidden ids return 404. Bank connections are private to the member who created them.
- Security-relevant actions write to `audit_log` via `app.sessions.audit`. Never log transaction contents.
- Settings come from `FA_*` env vars or files in `/run/secrets` (see `app/config.py`).
- Requests that end in an error roll back; commit explicitly first if a side effect must persist (see `_register_failure`).
- Procrastinate upgrades may ship SQL migrations: add them as a new Alembic revision.

## Do not

- Add dependencies without asking Robin first.
- Edit `.env`, files in `secrets/`, or production config without explicit approval.
- Commit or push without being asked.
- Disable tests, lint rules or type checks to get green; fix the cause.
