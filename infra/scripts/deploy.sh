#!/usr/bin/env bash
# Выкатывает окружение на сервере: ./deploy.sh <staging|production> <image-tag>
# Рядом должны лежать app/docker-compose.yml, edge/ и <env>.env.
# Все файлы, включая <env>.env (из секретов environment), кладёт сюда workflow Deploy.
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
[[ -f $ENV_FILE ]] || fail "нет файла $ENV_FILE (его создаёт workflow Deploy из секретов GitHub)"
env_value() { sed -n "s/^$1=//p" "$ENV_FILE"; }
[[ $(env_value APP_ENV) == "$ENV_NAME" ]] || fail "APP_ENV в $ENV_FILE должен быть $ENV_NAME"
APP_DOMAIN=$(env_value APP_DOMAIN)
[[ -n $APP_DOMAIN ]] || fail "в $ENV_FILE не задан APP_DOMAIN"

export ENV_FILE IMAGE_TAG
app() { docker compose -p "storymaker-$ENV_NAME" -f "$ROOT/app/docker-compose.yml" --env-file "$ENV_FILE" "$@"; }
edge() { docker compose -p storymaker-edge -f "$ROOT/edge/docker-compose.yml" "$@"; }

docker network inspect edge >/dev/null 2>&1 || docker network create edge >/dev/null

app pull
app up -d --wait db
app run --rm api alembic upgrade head
app up -d --wait --remove-orphans

mkdir -p "$ROOT/edge/sites"
printf '%s {\n\treverse_proxy storymaker-%s-web:80\n}\n' "$APP_DOMAIN" "$ENV_NAME" \
  >"$ROOT/edge/sites/$ENV_NAME.caddy"
edge up -d
for _ in $(seq 1 10); do
  edge exec -T caddy caddy reload --config /etc/caddy/Caddyfile && break
  sleep 2
done

docker image prune -f >/dev/null
echo "✓ $ENV_NAME → $IMAGE_TAG (https://$APP_DOMAIN)"
