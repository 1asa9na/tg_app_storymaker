#!/usr/bin/env bash
# Выкатывает окружение на сервере: ./deploy.sh <staging|production> <image-tag>
# Рядом должны лежать app/docker-compose.yml и <env>.env.
# Все файлы, включая <env>.env (из секретов environment), кладёт сюда workflow Deploy.
#
# Общий Caddy сервера этот скрипт не запускает. Контейнер caddy уже слушает 80/443
# и импортирует /opt/caddy/sites/*.caddy (см. docs/SETUP.md). Скрипт пишет туда сайт
# окружения и просит Caddy перечитать конфиг.
set -euo pipefail

usage="usage: deploy.sh <staging|production> <image-tag>"
ENV_NAME=${1:?$usage}
IMAGE_TAG=${2:?$usage}
ROOT=$(cd "$(dirname "$0")" && pwd)
ENV_FILE=$ROOT/$ENV_NAME.env
CADDY_SITES=${CADDY_SITES:-/opt/caddy/sites}
CADDY_CONTAINER=${CADDY_CONTAINER:-caddy}
CADDY_CONFIG=${CADDY_CONFIG:-/etc/caddy/Caddyfile}

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
# Студия — необязательный второй домен окружения на тот же web
STUDIO_DOMAIN=$(env_value STUDIO_DOMAIN)

# Каталог и контейнер можно переопределить в <env>.env, если общий Caddy лежит не в /opt/caddy
override=$(env_value CADDY_SITES)
[[ -n $override ]] && CADDY_SITES=$override
override=$(env_value CADDY_CONTAINER)
[[ -n $override ]] && CADDY_CONTAINER=$override
override=$(env_value CADDY_CONFIG)
[[ -n $override ]] && CADDY_CONFIG=$override

[[ -d $CADDY_SITES && -w $CADDY_SITES ]] ||
  fail "нет доступного каталога $CADDY_SITES — общий Caddy сервера ещё не подготовлен (docs/SETUP.md)"
docker container inspect "$CADDY_CONTAINER" >/dev/null 2>&1 ||
  fail "нет контейнера $CADDY_CONTAINER — сначала запустите общий Caddy (docs/SETUP.md)"
[[ $(docker inspect -f '{{.State.Running}}' "$CADDY_CONTAINER") == true ]] ||
  fail "контейнер $CADDY_CONTAINER не запущен"
docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' "$CADDY_CONTAINER" |
  grep -qw edge ||
  fail "контейнер $CADDY_CONTAINER не подключён к сети edge"

export ENV_FILE IMAGE_TAG
app() { docker compose -p "storymaker-$ENV_NAME" -f "$ROOT/app/docker-compose.yml" --env-file "$ENV_FILE" "$@"; }

docker network inspect edge >/dev/null 2>&1 || docker network create edge >/dev/null

app pull
app up -d --wait db
app run --rm api alembic upgrade head
# Тайтлы из репозитория, которых ещё нет в базе: импорт, сборка, публикация
app run --rm api python -m storymaker_api.studio seed
app up -d --wait --remove-orphans

site=$CADDY_SITES/storymaker-$ENV_NAME.caddy
tmp=$(mktemp "$CADDY_SITES/.storymaker-$ENV_NAME.caddy.XXXXXX")
printf '# storymaker %s — пишет deploy.sh\n%s {\n\treverse_proxy storymaker-%s-web:80\n}\n' \
  "$ENV_NAME" "$APP_DOMAIN${STUDIO_DOMAIN:+, $STUDIO_DOMAIN}" "$ENV_NAME" >"$tmp"
mv "$tmp" "$site"

reloaded=0
for _ in $(seq 1 10); do
  if docker exec "$CADDY_CONTAINER" caddy reload --config "$CADDY_CONFIG"; then
    reloaded=1
    break
  fi
  sleep 2
done
[[ $reloaded == 1 ]] ||
  fail "Caddy ($CADDY_CONTAINER) не перечитал $CADDY_CONFIG. Файл сайта уже записан: $site"

docker image prune -f >/dev/null
echo "✓ $ENV_NAME → $IMAGE_TAG (https://$APP_DOMAIN${STUDIO_DOMAIN:+, студия https://$STUDIO_DOMAIN})"
