# syntax=docker/dockerfile:1
FROM postgres:18-alpine
RUN apk add --no-cache restic tini
COPY backup.sh /usr/local/bin/backup.sh
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/backup.sh /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/entrypoint.sh"]
