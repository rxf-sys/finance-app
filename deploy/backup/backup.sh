#!/bin/sh
# Dumps the database and stores it encrypted with restic, then applies retention.
set -eu

PGPASSWORD="$(cat "${PGPASSWORD_FILE:?PGPASSWORD_FILE is required}")"
export PGPASSWORD

echo "$(date -Iseconds) backup started"
pg_dump --format=custom --no-owner \
  | restic backup --stdin --stdin-filename finance.dump --tag finance-db
restic forget --tag finance-db --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune
echo "$(date -Iseconds) backup finished"
