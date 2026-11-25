#!/bin/sh
# Runs backup.sh on the cron schedule in BACKUP_SCHEDULE (default 02:30 daily).
set -eu

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required}"
: "${RESTIC_PASSWORD_FILE:?RESTIC_PASSWORD_FILE is required}"

if ! restic cat config >/dev/null 2>&1; then
  echo "Initialising restic repository at ${RESTIC_REPOSITORY}"
  restic init
fi

echo "${BACKUP_SCHEDULE:-30 2 * * *} /usr/local/bin/backup.sh > /proc/1/fd/1 2>&1" > /etc/crontabs/root
echo "Backup schedule: ${BACKUP_SCHEDULE:-30 2 * * *}"
exec crond -f -l 8
