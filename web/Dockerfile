FROM caddy:2.11-builder AS builder
RUN xcaddy build --with github.com/mholt/caddy-ratelimit@v0.1.0

FROM caddy:2.11-alpine
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
LABEL org.opencontainers.image.source="https://github.com/50512/whoami-diagnostic"
COPY Caddyfile /etc/caddy/Caddyfile
