# Контекст сборки — корень репозитория: docker build -f infra/web/Dockerfile .
FROM node:22-slim AS build
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/player/package.json apps/player/
RUN pnpm install --frozen-lockfile --filter player
COPY apps/player apps/player
RUN pnpm --filter player build

FROM caddy:2.10-alpine
COPY infra/web/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /repo/apps/player/dist /srv/player
