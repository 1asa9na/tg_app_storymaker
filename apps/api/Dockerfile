# Контекст сборки — корень репозитория: docker build -f apps/api/Dockerfile .

# Движок сцен (packages/engine) отдельной папкой с node_modules: студия собирает тайтлы
# на сервере, а сцены компилирует Node.
FROM node:22-slim AS engine
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY apps/player/package.json apps/player/
COPY apps/studio/package.json apps/studio/
COPY packages/vn-renderer/package.json packages/vn-renderer/
COPY packages/game-ui/package.json packages/game-ui/
COPY packages/engine packages/engine
RUN pnpm --filter @storymaker/engine deploy --prod --legacy /engine

FROM python:3.13-slim AS build
RUN pip install --no-cache-dir uv==0.11.32
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY apps/api/ ./
RUN uv sync --locked --no-dev --no-editable

FROM python:3.13-slim
# libstdc++ нужна бинарнику node
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --home-dir /app app \
    && mkdir -p /srv/assets && chown app /srv/assets
WORKDIR /app
COPY --from=engine /usr/local/bin/node /usr/local/bin/node
COPY --from=engine /engine /app/engine
COPY --from=build /app /app
# Тайтлы из репозитория: при деплое импортируются в базу те, которых там ещё нет
COPY content/titles /app/content/titles
ENV PATH=/app/.venv/bin:$PATH \
    STORYMAKER_ENGINE_DIR=/app/engine \
    CONTENT_DIR=/app/content/titles \
    PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
CMD ["uvicorn", "storymaker_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
