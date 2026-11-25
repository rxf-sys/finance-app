# ADR 0001: Stack for Orynthia Finance

- Status: accepted (recorded afterwards on 25.11.2026; the code has used this stack since phase 0)
- Context date: 24.11.2026

## Context

The predecessor, Orynthia v1, is a NestJS 10 / Prisma 5 / React 18 monorepo with finance and
everyday modules in one app. The finance part needs a household data model, exact money handling,
background jobs for bank sync and notifications, and a small, auditable security surface. The
owner also runs other self-hosted FastAPI projects.

## Options

1. Extend the NestJS code of Orynthia v1.
2. New app on FastAPI, SQLAlchemy 2, Alembic and PostgreSQL, React 19 with TanStack Router and
   Query, Tailwind 4; jobs in Postgres via Procrastinate.
3. New app on Fastify/TypeScript like admin.rxf-sys.de v2.

## Decision

Option 2. Python keeps CSV parsing, money logic and bank mapping readable and testable against a
real Postgres (testcontainers). Procrastinate uses the existing database as job queue, so Redis is
not needed. The frontend types are generated from the OpenAPI schema, which turns API drift into a
CI failure.

## Consequences

- One database, no Redis; the `internal` Docker network keeps it off the internet.
- Strict mypy and ruff gates; schema changes only through reviewed Alembic revisions.
- Procrastinate upgrades may bring SQL migrations, which become their own Alembic revisions.
- The planned Orynthia Everyday should use the same stack so both apps share tooling, CI and
  security patterns (to be confirmed in an ADR in that repository).
