# Настройка окружений (этап 0)

Код, Docker-образы, CI и деплой-скрипт уже в репозитории. Ниже то, что делается руками один раз: боты, сервер, домен, Supabase и доступы для GitHub Actions.

Порядок такой: сначала стейджинг, прод — по той же схеме, когда понадобится.

## 1. Боты

В @BotFather:
1. `/newbot` — создать два бота: `<name>_staging_bot` и `<name>_bot`. Сохранить токены.
2. Для каждого бота: *Bot Settings → Configure Mini App → Enable Mini App*, URL — `https://staging.<домен>` для стейджинга и `https://app.<домен>` для прода.

   Этот адрес хранится у Telegram, и наш сервер его не меняет. Вебхук, кнопку меню и кнопку после `/start` сервер перерегистрирует при каждом деплое, а URL Mini App — нет. Поэтому **после смены `APP_DOMAIN` обновите URL и здесь**, иначе бот будет открывать старый домен, а браузер покажет `ERR_SSL_PROTOCOL_ERROR`. Короткая ссылка из `/newapp` меняется отдельно: `/myapps` → приложение → *Edit Web App URL*.
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
- студия стейджинга — `devstudio.<домен>`; студия прода — по желанию, например `studio.<домен>`

Сертификаты Let's Encrypt Caddy получит сам при первом деплое. Записи должны начать резолвиться до этого.

## 4. Секреты в GitHub

Всё, что нужно серверу, хранится в GitHub. Создайте *Settings → Environments* → `staging` и `production`, затем в *Environment secrets* каждого окружения заведите секреты из таблицы.

Workflow *Deploy* при каждой выкатке:
- собирает из этих секретов файл `/opt/storymaker/<окружение>.env`;
- пишет его на сервер с правами 600.

Руками на сервере ничего не правится. `APP_ENV` и `IMAGE_REPO` workflow подставляет сам.

| Секрет | Обязателен | Что это | Где взять |
|---|---|---|---|
| `DEPLOY_HOST` | да | IP или домен сервера | Панель провайдера VPS |
| `DEPLOY_USER` | да | Пользователь для деплоя | `deploy` (шаг 2) |
| `DEPLOY_PORT` | нет | Порт SSH, если не 22 | Настройки сервера |
| `DEPLOY_SSH_KEY` | да | Приватный SSH-ключ целиком, вместе со строками `BEGIN`/`END` | Файл `storymaker_deploy`, см. ниже |
| `DEPLOY_KNOWN_HOSTS` | да | Отпечаток сервера | На своей машине: `ssh-keyscan -p <порт> -t ed25519 <ip-сервера>` (флаги до адреса); строку вывода целиком |
| `APP_DOMAIN` | да | Домен окружения без `https://` | `staging.<домен>` или `app.<домен>` |
| `STUDIO_DOMAIN` | для студии | Домен студии без `https://`. Без него студия окружения не открывается | `devstudio.<домен>` для staging |
| `POSTGRES_PASSWORD` | да | Пароль базы | `openssl rand -hex 24` |
| `BOT_TOKEN` | да | Токен бота этого окружения | @BotFather (шаг 1) |
| `BOT_WEBHOOK_SECRET` | да | Секрет вебхука | `openssl rand -hex 32` |
| `S3_ENDPOINT_URL` | для `doctor` и с этапа 3 | Адрес S3 API Supabase вида `https://<ref>.storage.supabase.co/storage/v1/s3` — не Project URL | Supabase: *Storage → Settings → S3 Connection*, поле Endpoint (шаг 5) |
| `S3_REGION` | — " — | Регион проекта | Там же |
| `S3_ACCESS_KEY_ID` | — " — | ID ключа | Там же, создать ключ |
| `S3_SECRET_ACCESS_KEY` | — " — | Секрет ключа | Там же, показывается один раз |
| `SENTRY_DSN` | нет | Ошибки API | Sentry или GlitchTip |
| `PLAYER_SENTRY_DSN` | нет | Ошибки плеера | Там же, отдельный проект |

Ключ для деплоя (на своём компьютере):

```bash
ssh-keygen -t ed25519 -N "" -f storymaker_deploy
# storymaker_deploy.pub — на сервер, в ~deploy/.ssh/authorized_keys
# storymaker_deploy — целиком в секрет DEPLOY_SSH_KEY
```

Правила:
- **Значения у окружений разные:** два бота, два пароля, два проекта Supabase. Одинаковыми могут быть только `DEPLOY_*`, если окружения живут на одном сервере.
- **Значения — одной строкой, без кавычек.** Исключение — `DEPLOY_SSH_KEY`: он многострочный, но в файл окружения не попадает.
- **`POSTGRES_PASSWORD` задаётся один раз.** Postgres берёт его только при первом создании базы. Если потом поменять секрет, пароль в базе не изменится, а API перестанет к ней подключаться.
- **Как ведёт себя деплой без секретов:** пока не задан `DEPLOY_HOST`, деплой пропускается с предупреждением. Если хост задан, а обязательного секрета нет, деплой падает и перечисляет недостающие.

## 5. Supabase (только Storage)

По проекту на окружение: стейджинг и прод, оба на бесплатном тарифе (см. `docs/PLAN.md` §10.1). Регион — Франкфурт.

1. *Storage → Settings → S3 Connection*: включить S3-протокол, создать access key. Endpoint, регион и пару ключей — в секреты `S3_*` окружения (шаг 4). Project URL и ключи `anon` и `service_role` для S3 не подходят и не нужны.
2. Бакеты `assets` и `originals`, оба **приватные**. Для `assets` — лимит размера файла и разрешённые типы `image/webp`, `audio/mp4`, `audio/mpeg`.
3. На `storage.objects` не создавать ни одной политики.
4. Выключить: *Project Settings → Data API*; в *Authentication* — все способы входа, регистрацию и анонимный вход; в *Storage → Settings* — Image Transformations.

## 6. Настройки репозитория

1. *Deployment branches and tags* в каждом окружении:
   - `staging` — только `develop`;
   - `production` — только `master`.

   Тогда фича-ветка не сможет выкатиться ни в одно окружение даже вручную.
2. Для `production` включить *Required reviewers*: прод выкатывается только после подтверждения.
3. *Settings → General → Default branch* — `develop`: в неё по умолчанию открываются PR фич.
4. *Settings → Rules → Rulesets* для `master` и `develop`:
   - изменения только через PR;
   - обязательные проверки `api` и `web` из workflow CI;
   - запрет force push и удаления.

## 7. Первый деплой

Ветки: `master` — прод, `develop` — стейджинг, фичи — от `develop` и обратно в неё через PR.

- **Стейджинг:** мердж фичи в `develop`. Workflow *Deploy* прогонит проверки, соберёт образы `ghcr.io/1asa9na/tg_app_storymaker/{api,web}:<sha>` и выкатит их скриптом `deploy.sh`: миграции, запуск, регистрация домена во внешнем Caddy.
- **Прод:** PR из `develop` в `master`. После мерджа тот же путь, но выкатка ждёт подтверждения в environment `production`.
- **Повторная выкатка** без нового коммита: *Actions → Deploy → Run workflow*.

## 8. Проверка

На сервере:

```bash
docker exec storymaker-staging-api-1 python -m storymaker_api.doctor
```

Скрипт запускается внутри работающего контейнера API с его настройками. Он проверяет базу, Telegram Bot API (бот и вебхук) и Supabase Storage: запись, presigned-загрузку и сохранение `Cache-Control`. Это спайк из `docs/PLAN.md` §10.4. Для прода — `storymaker-production-api-1`.

Затем в Telegram: открыть стейджинг-бота → `/start` → «Открыть». В каталоге — тайтлы из `content/titles` (при первом деплое они импортируются в базу и публикуются сами).

## 9. Студия: первый вход

1. A-запись `devstudio.<домен>` и секрет `STUDIO_DOMAIN` в окружении (шаги 3 и 4), перезапуск деплоя.
2. Каждый, кого добавляете в команду, один раз открывает бота и нажимает `/start`: так он появляется в базе.
3. На сервере (Telegram id можно узнать у @userinfobot):

   ```bash
   docker exec storymaker-staging-api-1 python -m storymaker_api.studio staff add <telegram_id> admin
   docker exec storymaker-staging-api-1 python -m storymaker_api.studio staff list
   ```

   Роли: `admin` — всё; `designer` — импорт, сборка, публикация; `writer` — пока только смотрит (редактор сцен — этап 4). Убрать: `staff remove <telegram_id>`.
4. В боте — `/studio`: бот пришлёт ссылку входа. Она действует 10 минут и один раз; сессия в студии — 30 дней.

Тайтлы из `content/titles` попадают в базу только при первом деплое. Дальше их ведут в студии: «Скачать архивом» → правка YAML → «Импортировать папку» → «Собрать» → «Опубликовать».

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
