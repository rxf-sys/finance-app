# syntax=docker/dockerfile:1
# Only the client tools are needed: pg_dump must match the server's major version (18).
FROM alpine:3.24
RUN apk add --no-cache postgresql18-client restic tini \
    && pg_dump --version | grep -q "(PostgreSQL) 18\."
COPY backup.sh /usr/local/bin/backup.sh
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/backup.sh /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/entrypoint.sh"]
