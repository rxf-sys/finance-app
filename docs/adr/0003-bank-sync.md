# ADR 0003: Bank sync through Enable Banking, same pipeline as CSV

- Status: accepted (recorded afterwards on 25.11.2026)

## Context

PSD2 access needs a licensed provider. CSV import already existed (presets for DKB, ING,
Sparkasse CAMT, N26) with dedupe, rules, transfer pairing and contract matching.

## Decision

- Enable Banking as provider: the member gives consent in the bank's flow, the session is stored
  AES-256-GCM-encrypted.
- The worker syncs connections hourly when the last sync is older than 6 hours; members can request a
  manual sync.
- Synced rows run through exactly the same pipeline as a CSV import, so dedupe and categorisation
  behave identically for both sources.
- Expiring consent and failed syncs become notifications.

## Consequences

- Without Enable Banking credentials the app works with CSV import only.
- Setting up the provider currently needs manual changes in `compose.yaml`
  (see [deployment.md](../deployment.md)); a guided setup is on the roadmap.
