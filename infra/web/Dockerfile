# Контекст сборки — корень репозитория: docker build -f infra/web/Dockerfile .
FROM node:22-slim AS build
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY apps/player/package.json apps/player/
COPY apps/studio/package.json apps/studio/
COPY packages/engine/package.json packages/engine/
COPY packages/vn-renderer/package.json packages/vn-renderer/
COPY packages/game-ui/package.json packages/game-ui/
RUN pnpm install --frozen-lockfile --filter "player..." --filter "studio..."
COPY apps/player apps/player
COPY apps/studio apps/studio
COPY packages packages
RUN pnpm --filter player build && pnpm --filter studio build

FROM caddy:2.10-alpine
COPY infra/web/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /repo/apps/player/dist /srv/player
COPY --from=build /repo/apps/studio/dist /srv/studio
