#!/usr/bin/env bash
# Выкатывает окружение на сервере: ./deploy.sh <staging|production> <image-tag>
# Рядом должны лежать app/docker-compose.yml и <env>.env.
# Все файлы, включая <env>.env (из секретов environment), кладёт сюда workflow Deploy.
# Caddy этот скрипт не запускает и не настраивает: web слушает 127.0.0.1:$WEB_PORT.
set -euo pipefail

usage="usage: deploy.sh <staging|production> <image-tag>"
ENV_NAME=${1:?$usage}
IMAGE_TAG=${2:?$usage}
ROOT=$(cd "$(dirname "$0")" && pwd)
ENV_FILE=$ROOT/$ENV_NAME.env

fail() {
  echo "✗ $*" >&2
  exit 1
}

[[ $ENV_NAME == staging || $ENV_NAME == production ]] || fail "$usage"
docker compose version >/dev/null 2>&1 ||
  fail "нет плагина docker compose: sudo apt install docker-compose-v2 (или docker-compose-plugin)"
[[ -f $ENV_FILE ]] || fail "нет файла $ENV_FILE (его создаёт workflow Deploy из секретов GitHub)"
env_value() { sed -n "s/^$1=//p" "$ENV_FILE"; }
[[ $(env_value APP_ENV) == "$ENV_NAME" ]] || fail "APP_ENV в $ENV_FILE должен быть $ENV_NAME"
APP_DOMAIN=$(env_value APP_DOMAIN)
[[ -n $APP_DOMAIN ]] || fail "в $ENV_FILE не задан APP_DOMAIN"
STUDIO_DOMAIN=$(env_value STUDIO_DOMAIN)
WEB_PORT=$(env_value WEB_PORT)
[[ $WEB_PORT =~ ^[0-9]+$ ]] || fail "в $ENV_FILE не задан WEB_PORT — порт на 127.0.0.1, куда смотрит Caddy сервера"

export ENV_FILE IMAGE_TAG
app() { docker compose -p "storymaker-$ENV_NAME" -f "$ROOT/app/docker-compose.yml" --env-file "$ENV_FILE" "$@"; }

app pull
app up -d --wait db
app run --rm api alembic upgrade head
# Тайтлы из репозитория, которых ещё нет в базе: импорт, сборка, публикация
app run --rm api python -m storymaker_api.studio seed
app up -d --wait --remove-orphans

docker image prune -f >/dev/null
echo "✓ $ENV_NAME → $IMAGE_TAG (https://$APP_DOMAIN${STUDIO_DOMAIN:+, студия https://$STUDIO_DOMAIN}, 127.0.0.1:$WEB_PORT)"
