# API для плеера

Все запросы — с заголовком `Authorization: tma <initDataRaw>` из Telegram Mini App. Без него или с поддельной подписью — `401`. Пользователь создаётся при первом запросе.

На стейджинге схема и песочница запросов — `https://staging.bgylke8.online/api/docs` (на проде выключены).

## Платформа

| Запрос | Что возвращает |
|---|---|
| `GET /api/me` | Профиль из Telegram, `level`, `xp`. Обновляет имя и язык |
| `GET /api/profile` | `xp`, `level`, `level_xp`, `next_level_xp` и `achievements: [{key, name, title, unlocked_at}]` |
| `GET /api/titles` | Каталог: `[{slug, name, days, save: {day, finished} \| null}]` |

## Тайтл

| Запрос | Что возвращает |
|---|---|
| `GET /api/titles/{slug}/game` | Данные для отображения: слоты, ресурсы, характеристики, персонажи, лимит подарков в день (`gifts_per_day`), карта, локации, предметы, квесты с текстами журнала, достижения. Без условий, эффектов и событий |
| `GET /api/titles/{slug}/state` | Экран игры (ниже). Первый запрос начинает игру |
| `POST /api/titles/{slug}/actions` | Действие → экран игры + `outcome` |
| `GET /api/titles/{slug}/scenes/{key}` | `{key, revision, json}` — скомпилированная сцена для inkjs. Отдаётся только сцена, которая сейчас в очереди первой, иначе `404` |
| `POST /api/titles/{slug}/restart` | `{request_id, revision?}` → начать заново. Опыт и достижения аккаунта остаются |

### Экран игры

```jsonc
{
  "revision": 4,                       // присылайте его в следующем действии
  "account": { "xp": 55, "level": 2, "level_xp": 50, "next_level_xp": 150, "level_up": false },
  "time": { "day": 1, "slot": "evening", "weekday": "пн" },
  "resources": { "energy": { "value": 30, "max": 100, "next_at": "2026-10-26T06:10:00Z" } },
  "locations": [
    { "id": "gym", "name": "Спортзал", "point": { "x": 0.7, "y": 0.6 },
      "lock": null, "characters": ["anna"] }
  ],
  "here": {
    "location": "gym",
    "characters": ["anna"],
    "activities": [
      { "id": "workout", "name": "Тренировка", "description": "",
        "cost": { "slots": 1, "energy": 20 }, "effects": { "stat.fitness": 3 },
        "with_character": null, "lock": "Не хватает: энергия (нужно 20)" }
    ]
  },
  "can_sleep": true,
  "pending_scene": "anna_meet",        // пока не null — другие действия недоступны
  "state": { /* сохранение целиком: stats, affection, items, flags, quests… */ }
}
```

`lock` — причина, почему сейчас нельзя: показывайте её на неактивной кнопке. `null` — можно. `next_at` — когда восстановится следующая единица ресурса, для таймера на клиенте.

### Действия

```jsonc
POST /api/titles/demo/actions
{
  "request_id": "6f1c…",   // UUID, новый на каждое нажатие
  "revision": 4,           // необязательно, но лучше присылать
  "action": { "type": "activity", "id": "workout" }
}
```

| `action` | Что делает |
|---|---|
| `{type: "go", location}` | Перейти в локацию |
| `{type: "leave"}` | Выйти на карту |
| `{type: "activity", id}` | Занятие в текущей локации |
| `{type: "gift", item, character}` | Подарить предмет персонажу рядом |
| `{type: "use", item}` | Использовать расходник |
| `{type: "sleep"}` | Лечь спать — следующее утро |
| `{type: "scene_complete", scene, effects}` | Сцена досмотрена; `effects` — то, что вернул `SceneRunner.collectedEffects()` |

К экрану игры ответ добавляет `outcome`:

```jsonc
"outcome": {
  "changes": [{ "path": "stat.fitness", "delta": 3 }, { "path": "resource.energy", "delta": -20 }],
  "scenes": ["first_workout"],        // поставлены в очередь этим действием
  "xp": 5,                            // опыт аккаунта за действие
  "achievements": ["first_date"],     // новые достижения
  "quests": [{ "quest": "anna_trust", "status": "done", "stage": null }],
  "new_day": false
}
```

### Повторы и ошибки

- **Тот же `request_id` ещё раз** (обрыв сети, двойной тап) — тот же ответ, ничего не применяется повторно. Повторяйте запрос с тем же `request_id`, пока не получите ответ.
- **`409`** — действие не принято, состояние не изменилось. В теле `{"detail": {"code", "message"}}`, `message` можно показать игроку:

| `code` | Когда |
|---|---|
| `stale` | `revision` устарела: игра изменилась в другой вкладке или на другом устройстве. Перезапросите `/state` |
| `locked` | Локация или занятие сейчас недоступны |
| `scene_pending` | Сначала досмотрите сцену |
| `bad_scene` | Эта сцена сейчас не идёт |
| `effect_not_allowed` | Сцена прислала эффект не из своего белого списка |
| `not_here`, `no_item`, `gift_limit`, `cant_sleep`, `unknown` | Подарок, предмет, сон, неизвестный ключ |
| `finished` | Тайтл пройден: можно начать заново |
| `save_incompatible` | Тайтл обновился так, что сохранение не подходит: только рестарт |

- **`404`** — нет такого тайтла или сцена сейчас не идёт. **`422`** — неправильная форма запроса.

## Превью и песочница

Те же маршруты игры, что у тайтла, но с другим сохранением (`sandbox:<сборка>`); опыт и достижения аккаунту не начисляются.

| Префикс | Кто | Вход |
|---|---|---|
| `/api/preview/{token}/…` | Сотрудник на телефоне по кнопке из бота (`?preview=<token>` или `startapp=preview_<token>`) | `tma <initData>` + пользователь в команде |
| `/api/studio/titles/{slug}/builds/{id}/sandbox/…` | Студия | cookie-сессия студии; ещё `PUT debug/state` и `GET debug/log` |

## Тайтлы на сервере

Игроки видят опубликованные тайтлы: у каждого в базе активная сборка, её выбирают и меняют в студии (`devstudio.<домен>`, см. docs/SETUP.md §9). Новая версия доходит до игроков со следующего запроса, без деплоя. Тайтлы из `content/titles` попадают в базу при первом деплое.

Локально — так же, как на сервере:

```bash
cd apps/api
CONTENT_DIR=../../content/titles uv run python -m storymaker_api.studio seed
```
