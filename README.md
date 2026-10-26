# StoryMaker

Платформа dating sim-новелл внутри Telegram Mini App: один бот — каталог тайтлов с общим прогрессом игрока. В тайтле — сюжетные сцены и игровой цикл (время суток, энергия, занятия, инвентарь, квесты), который исполняет серверный движок по данным из внутренней студии.

Стек: Python (FastAPI, aiogram) на бэкенде, TypeScript/React для плеера и студии, сюжеты на ink, PostgreSQL, файлы в S3 (Supabase Storage).

- [План разработки MVP](docs/PLAN.md)
- [Настройка окружений и локальная разработка](docs/SETUP.md)
- [Ассеты: технические требования](docs/ASSETS.md)

Ветки: `master` — прод, `develop` — стейджинг, фичи — от `develop` и обратно через PR.

## Структура

```
apps/api/        Python: API, бот, миграции (uv)
apps/player/     Telegram Mini App (Vite + React)
infra/web/       образ web: Caddy + собранный плеер
infra/app/       docker compose одного окружения (db, api, web)
infra/edge/      внешний Caddy: TLS и домены окружений
infra/dev/       Postgres для локальной разработки
infra/scripts/   deploy.sh — выкатка на сервере
.github/         CI (проверки) и Deploy (образы → GHCR → сервер)
```
