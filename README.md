# finance-app

> **Status:** In development (phase 3 in code, not in production yet) · planned product name **Orynthia Finance** · **As of:** 2026-11-25 · Part of my [portfolio](https://portfolio.rxf-sys.de/#projects)

Self-hosted household finance app: accounts, categories, contracts and budgets for one household with
several members. Runs as a Docker Compose stack, published through Cloudflare Tunnel behind Cloudflare Access.

Status: **Phase 3** – balance forecast for 1 to 3 months (confirmed contracts plus median income and
variable spending), savings goals (linked to an account or with manual contributions), yearly and
category reports, transaction export as CSV or Excel, installable as a PWA. Built on Phase 2 (bank sync
through Enable Banking, contract detection with cancellation deadlines and letters, budgets, "frei
verfügbar", in-app notifications), Phase 1 (accounts, CSV import with bank presets, categories with
learning rules, transactions with splits, tags and transfer pairing, dashboard) and Phase 0 (login with
password + TOTP or passkeys, households with invites, Cloudflare Access check, deployment stack, CI).

## Quick start (development)

```sh
docker compose -f compose.dev.yaml up -d          # Postgres on 127.0.0.1:5432

cd backend
uv sync
export FA_DB_PASSWORD=devpass FA_COOKIE_SECURE=false FA_ENCRYPTION_KEY="$(uv run python -m app.cli generate-key)"
uv run alembic upgrade head
uv run python -m app.cli create-owner --email you@example.com --name "Your Name" --household "Zuhause"
# or, on an empty database: a fictional demo household (demo@example.org) for trying it out
# uv run python -m app.cli seed-demo
uv run uvicorn app.main:app --reload               # API on :8000, docs on /api/docs

cd ../frontend
pnpm install
pnpm dev                                           # UI on http://localhost:5173
```

## Production

See [docs/deployment.md](docs/deployment.md) for the Proxmox VM, Cloudflare Tunnel and Access setup.

More documentation: [architecture](docs/architecture.md), [decisions (ADRs)](docs/adr/),
[roadmap](docs/roadmap.md), [design and contrast](docs/design.md).

## Security model

1. Cloudflare Access in front of the whole host (allow-list of household e-mails).
2. The API verifies the `Cf-Access-Jwt-Assertion` header on every request except `/api/health`.
3. App login: passkey, or Argon2id password plus optional TOTP; server-side sessions in an
   `HttpOnly`, `Secure`, `SameSite=Strict` cookie; lockout after repeated failures.
4. TOTP secrets are AES-256-GCM encrypted with a key that lives only in a Docker secret.
5. The database is on an internal Docker network without internet access.
