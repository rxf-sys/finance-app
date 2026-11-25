# Roadmap: Orynthia Finance

Status: 25.11.2026. Order, not dates. Phases 0 to 3 are implemented (see README); the app is not in
production yet.

## Phase 4: production and parity with Orynthia v1

- Deploy on the own server, run as beta in the own household, verify backups and a restore.
- Import the finance data of Orynthia v1 (export there, CSV import here).
- Close the gaps to v1: investment tracking (depot), loan accounts, alerts for unusually large
  bookings, savings potential.
- Guided Enable Banking setup instead of manual compose edits.
- Coverage gate in CI.

## Phase 5: Orynthia family

- ICS feed of cancellation deadlines for the calendar of Orynthia Everyday.
- Read-only token for "available to spend" on the Everyday home screen.
- Draft expenses from completed shopping lists in Everyday.
- Shared design tokens and sign-in pattern with Everyday (see the Orynthia concept in the portfolio).

## Later

- English UI (would need an i18n library; new dependency, needs approval).
- Several households per user.
