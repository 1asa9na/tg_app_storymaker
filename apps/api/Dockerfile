# Контекст сборки — корень репозитория: docker build -f apps/api/Dockerfile .

# Тайтлы: YAML и сцены ink → JSON-сборки. Здесь нужен Node для компиляции сцен,
# в итоговом образе его нет.
FROM node:22-slim AS titles
RUN corepack enable
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY apps/player/package.json apps/player/
COPY packages/vn-renderer/package.json packages/vn-renderer/
COPY packages/game-ui/package.json packages/game-ui/
COPY packages/engine packages/engine
RUN pnpm install --frozen-lockfile --filter @storymaker/engine
WORKDIR /repo/apps/api
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --python 3.13
COPY apps/api/ ./
COPY content /repo/content
RUN uv run --locked --no-dev python -m storymaker_api.game build ../../content/titles --out /titles

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
RUN useradd --system --uid 10001 --home-dir /app app \
    && mkdir -p /srv/assets && chown app /srv/assets
WORKDIR /app
COPY --from=build /app /app
COPY --from=titles /titles /app/titles
ENV PATH=/app/.venv/bin:$PATH \
    TITLES_DIR=/app/titles \
    PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
CMD ["uvicorn", "storymaker_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
