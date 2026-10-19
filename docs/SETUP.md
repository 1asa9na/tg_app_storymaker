# Настройка окружений (этап 0)

Код, Docker-образы, CI и деплой-скрипт уже в репозитории. Ниже то, что делается руками один раз: боты, сервер, домен, Supabase и доступы для GitHub Actions.

Порядок такой: сначала стейджинг, прод — по той же схеме, когда понадобится.

## 1. Боты

В @BotFather:
1. `/newbot` — создать два бота: `<name>_staging_bot` и `<name>_bot`. Сохранить токены.
2. Для каждого бота: *Bot Settings → Configure Mini App → Enable Mini App*, URL — `https://staging.<домен>` для стейджинга и `https://app.<домен>` для прода.
3. По желанию: `/newapp` — короткое имя для прямой ссылки `t.me/<bot>/<app>` (понадобится для диплинков `startapp`).

Кнопку меню «Читать» и команду `/start` API настраивает сам при каждом запуске.

Для локальной разработки заведите третьего, личного dev-бота: локальный запуск через polling снимает вебхук у бота, чей токен использован.

## 2. Сервер

- VPS у российского провайдера (Selectel, Timeweb Cloud, Yandex Cloud): Ubuntu 24.04, от 2 vCPU и 4 ГБ RAM, канал от 100 Мбит/с с включённым трафиком.
- Открыть порты 22, 80, 443 (TCP) и 443 (UDP, для HTTP/3).
- Установить Docker Engine с плагином compose: https://docs.docker.com/engine/install/ubuntu/
- Пользователь для деплоя:

```bash
sudo adduser --disabled-password deploy
sudo usermod -aG docker deploy
sudo mkdir -p /opt/storymaker && sudo chown deploy: /opt/storymaker
```

## 3. DNS

A-записи на IP сервера:
- `staging.<домен>`
- `app.<домен>`

Сертификаты Let's Encrypt Caddy получит сам при первом деплое. Записи должны начать резолвиться до этого.

## 4. Файлы окружений на сервере

От пользователя `deploy`:

```bash
cd /opt/storymaker
# env.example появится после первого деплоя; можно взять из infra/env.example
cp env.example staging.env && chmod 600 staging.env
openssl rand -hex 24   # → POSTGRES_PASSWORD
openssl rand -hex 32   # → BOT_WEBHOOK_SECRET
```

Заполнить `staging.env`: `APP_ENV=staging`, `APP_DOMAIN`, пароль базы, токен стейджинг-бота, секрет вебхука, S3-ключи (шаг 5). Для прода — `production.env` с `APP_ENV=production` и своими значениями: ни пароли, ни токены, ни ключи между окружениями не переиспользуются.

## 5. Supabase (только Storage)

По проекту на окружение: стейджинг и прод, оба на бесплатном тарифе (см. `docs/PLAN.md` §9.1). Регион — Франкфурт.

1. *Storage → Settings → S3 Connection*: включить S3-протокол, создать access key. Endpoint, регион и пару ключей — в `S3_*` файла окружения.
2. Бакеты `assets` и `originals`, оба **приватные**. Для `assets` — лимит размера файла и разрешённые типы `image/webp`, `audio/mp4`, `audio/mpeg`.
3. На `storage.objects` не создавать ни одной политики.
4. Выключить: *Project Settings → Data API*; в *Authentication* — все способы входа, регистрацию и анонимный вход; в *Storage → Settings* — Image Transformations.

## 6. GitHub Actions

1. Ключ для деплоя (на своём компьютере):

```bash
ssh-keygen -t ed25519 -N "" -f storymaker_deploy
# публичную часть — на сервер, в ~deploy/.ssh/authorized_keys
ssh-keyscan -t ed25519 <ip-сервера>   # → DEPLOY_KNOWN_HOSTS
```

2. *Settings → Environments*: создать `staging` и `production`. В каждом:
   - Variables: `DEPLOY_HOST` (IP или домен сервера), `DEPLOY_USER` (`deploy`);
   - Secrets: `DEPLOY_SSH_KEY` (содержимое `storymaker_deploy`), `DEPLOY_KNOWN_HOSTS` (вывод `ssh-keyscan`).
3. Для `production` включить *Required reviewers* — прод выкатывается только после подтверждения.

Пока `DEPLOY_HOST` не задан, workflow собирает образы и пропускает деплой с предупреждением.

## 7. Первый деплой

- **Стейджинг:** мердж в `main`. Workflow *Deploy* прогонит проверки, соберёт образы `ghcr.io/1asa9na/tg_app_storymaker/{api,web}:<sha>` и выкатит их скриптом `deploy.sh`: миграции, запуск, регистрация домена во внешнем Caddy.
- **Прод:** *Actions → Deploy → Run workflow → production*.

## 8. Проверка

На сервере:

```bash
cd /opt/storymaker
docker compose -p storymaker-staging -f app/docker-compose.yml --env-file staging.env \
  run --rm api python -m storymaker_api.doctor
```

Скрипт проверяет базу, Telegram Bot API (бот и вебхук) и Supabase Storage: запись, presigned-загрузку и сохранение `Cache-Control`. Это и есть спайк из `docs/PLAN.md` §9.4.

Затем в Telegram: открыть стейджинг-бота → `/start` → «Открыть». Должно появиться «Привет, <имя>!».

## Ошибки (Sentry)

`SENTRY_DSN` и `PLAYER_SENTRY_DSN` необязательны. Если sentry.io недоступен из РФ или неудобен по оплате, подойдёт GlitchTip — он совместим с SDK Sentry, меняется только DSN.

## Локальная разработка

```bash
docker compose -f infra/dev/docker-compose.yml up -d   # Postgres (+ база storymaker_test для тестов)

cd apps/api
cp .env.example .env                                   # вписать токен dev-бота
uv sync
uv run alembic upgrade head
uv run uvicorn storymaker_api.main:create_app --factory --reload
uv run python -m storymaker_api.polling                # бот без вебхука, в отдельном терминале
uv run pytest

cd ../..
pnpm install
pnpm dev                                               # плеер на :5173, /api проксируется в :8000
pnpm lint && pnpm typecheck
```

Вне Telegram плеер показывает «Откройте приложение через бота». Чтобы открыть локальную версию внутри Telegram, нужен HTTPS-туннель до `:5173` и его адрес в настройках Mini App dev-бота.
