# ADR 0002: Household with shared and private data

- Status: accepted (recorded afterwards on 25.11.2026)

## Context

Orynthia v1 stored everything per user. Households share some accounts (rent, groceries) but not
all (a personal credit card). Visibility rules spread over many endpoints are easy to get wrong.

## Decision

- Every record belongs to a household; every query filters by the caller's household
  (`CurrentMember`).
- Accounts and savings goals are `shared` or `private`; private ones are visible only to their owner.
  A transaction is visible when its account is; a contract when it has no account or a visible one;
  a savings goal linked to an account also needs that account to be visible.
- `app/finance/access.py` is the only place that decides visibility. Hidden ids answer 404, not 403,
  so their existence does not leak.
- Bank connections are private to the member who created them.
- Each new endpoint gets an isolation test.

## Consequences

- One user belongs to one household for now (`app/models/identity.py`); several households per user
  would need a household switch in the session.
- Reports and the forecast respect the same visibility, because they read through `access.py`.
