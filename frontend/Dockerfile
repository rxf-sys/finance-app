# syntax=docker/dockerfile:1
FROM node:22.23.5-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM caddy:2.11.9-alpine
RUN adduser -D -H -u 10002 web && chown -R web /data /config
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
USER web
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD ["wget", "-q", "--spider", "http://127.0.0.1:8080/"]
