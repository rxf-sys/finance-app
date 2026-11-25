# finance-app

Self-hosted household finance app: accounts, categories, contracts and budgets for one household with
several members. Runs as a Docker Compose stack, published through Cloudflare Tunnel behind Cloudflare Access.

Status: **Phase 0** – login (password + TOTP, passkeys), households with invites, Cloudflare Access check,
deployment stack, CI. Accounts and CSV import follow in Phase 1.

## Quick start (development)

```sh
docker compose -f compose.dev.yaml up -d          # Postgres on 127.0.0.1:5432

cd backend
uv sync
export FA_DB_PASSWORD=devpass FA_COOKIE_SECURE=false FA_ENCRYPTION_KEY="$(uv run python -m app.cli generate-key)"
uv run alembic upgrade head
uv run python -m app.cli create-owner --email you@example.com --name "Your Name" --household "Zuhause"
uv run uvicorn app.main:app --reload               # API on :8000, docs on /api/docs

cd ../frontend
pnpm install
pnpm dev                                           # UI on http://localhost:5173
```

## Production

See [docs/deployment.md](docs/deployment.md) for the Proxmox VM, Cloudflare Tunnel and Access setup.

## Security model

1. Cloudflare Access in front of the whole host (allow-list of household e-mails).
2. The API verifies the `Cf-Access-Jwt-Assertion` header on every request except `/api/health`.
3. App login: passkey, or Argon2id password plus optional TOTP; server-side sessions in an
   `HttpOnly`, `Secure`, `SameSite=Strict` cookie; lockout after repeated failures.
4. TOTP secrets are AES-256-GCM encrypted with a key that lives only in a Docker secret.
5. The database is on an internal Docker network without internet access.
