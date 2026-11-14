FROM node:22-alpine AS build-dist
WORKDIR /app
RUN corepack enable pnpm
COPY app/package.json app/pnpm-lock.yaml app/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY app/ ./
RUN pnpm run build

FROM caddy:2.11-builder AS builder
RUN xcaddy build --with github.com/mholt/caddy-ratelimit@v0.1.0

FROM caddy:2.11-alpine
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
LABEL org.opencontainers.image.source="https://github.com/50512/whoami-diagnostic" \
      org.opencontainers.image.licenses="MIT"
COPY --from=repo LICENSE /licenses/LICENSE
COPY caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build-dist /app/dist /srv
