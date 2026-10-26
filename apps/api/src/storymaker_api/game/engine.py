"""Игровой движок: действия игрока, время, ресурсы, события и квесты.

Чистая логика без базы и сети: на вход — данные тайтла, сохранение, действие и текущее время,
на выход — новое сохранение и что изменилось. Тот же код работает в API, песочнице и симуляторе.
"""

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from storymaker_api.game.conditions import holds
from storymaker_api.game.schema import Activity, Effects, Title
from storymaker_api.game.state import GameState, PendingScene, QuestState, ResourceState


class ActionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Go(BaseModel):
    type: Literal["go"]
    location: str


class Leave(BaseModel):
    type: Literal["leave"]


class DoActivity(BaseModel):
    type: Literal["activity"]
    id: str


class Gift(BaseModel):
    type: Literal["gift"]
    item: str
    character: str


class Use(BaseModel):
    type: Literal["use"]
    item: str


class Sleep(BaseModel):
    type: Literal["sleep"]


class SceneComplete(BaseModel):
    type: Literal["scene_complete"]
    scene: str
    #: Эффекты, которые вернула сцена (формат движка сцен), — проверяются по белому списку.
    effects: list[dict[str, Any]] = []


Action = Annotated[
    Go | Leave | DoActivity | Gift | Use | Sleep | SceneComplete, Field(discriminator="type")
]


@dataclass
class Change:
    path: str
    delta: int


@dataclass
class Outcome:
    state: GameState
    changes: list[Change] = field(default_factory=list)
    #: Сцены, поставленные в очередь этим действием.
    scenes: list[str] = field(default_factory=list)
    #: Опыт аккаунта и новые достижения — их применяет платформа.
    xp: int = 0
    achievements: list[str] = field(default_factory=list)
    #: Квесты, которые начались, продвинулись или завершились: (квест, статус, этап).
    quests: list[tuple[str, str, str | None]] = field(default_factory=list)
    new_day: bool = False


def scene_effects_to_effects(raw: list[dict[str, Any]]) -> Effects:
    """Эффекты из формата движка сцен (`{"op": "affection", ...}`) в формат данных тайтла."""
    add: dict[str, int] = {}
    flags: dict[str, bool] = {}
    started: list[str] = []
    advanced: list[str] = []
    achievements: list[str] = []

    def plus(path: str, amount: int) -> None:
        add[path] = add.get(path, 0) + amount

    for effect in raw:
        match effect["op"]:
            case "affection":
                plus(f"affection.{effect['character']}", effect["delta"])
            case "stat":
                plus(f"stat.{effect['stat']}", effect["delta"])
            case "give":
                plus(f"item.{effect['item']}", effect["count"])
            case "take":
                plus(f"item.{effect['item']}", -effect["count"])
            case "flag":
                flags[f"flag.{effect['flag']}"] = effect["value"]
            case "start_quest":
                started.append(effect["quest"])
            case "advance_quest":
                advanced.append(effect["quest"])
            case "xp":
                plus("global.xp", effect["amount"])
            case "achievement":
                achievements.append(effect["key"])
    return Effects(
        add=add,
        set=flags,
        start_quest=started,
        advance_quest=advanced,
        achievement=achievements,
    )


class Engine:
    def __init__(self, title: Title) -> None:
        self.title = title
        self.slots = title.slot_ids

    # ── Состояние ─────────────────────────────────────────────────────────

    def new_game(self, now: datetime) -> GameState:
        config = self.title.config
        state = GameState(
            title=self.title.id,
            location=config.start.location,
            resources={
                key: ResourceState(value=resource.start)
                for key, resource in config.resources.items()
            },
            stats={key: stat.start for key, stat in config.stats.items()},
            affection={key: char.affection_start for key, char in self.title.characters.items()},
            items=dict(config.start.items),
            flags=dict.fromkeys(config.start.flags, True),
        )
        for key, resource in config.resources.items():
            if resource.regen and resource.max is not None and resource.start < resource.max:
                state.resources[key].anchor = now
        outcome = Outcome(state=state)
        self._fire("day_start", outcome, now)
        self._check_quests(outcome, now)
        return outcome.state

    def refresh(self, state: GameState, now: datetime) -> GameState:
        """Досчитывает восстановление ресурсов к моменту now."""
        state = state.model_copy(deep=True)
        self._regen(state, now)
        return state

    def read(self, state: GameState, path: str) -> Any:
        """Значение по пути условия, например affection.anna или time.slot."""
        head, _, rest = path.partition(".")
        match head:
            case "stat":
                return state.stats.get(rest, 0)
            case "resource":
                resource = state.resources.get(rest)
                return resource.value if resource else 0
            case "affection":
                return state.affection.get(rest, 0)
            case "item":
                return state.items.get(rest, 0)
            case "flag":
                return state.flags.get(rest, False)
            case "event":
                return rest in state.events_seen
            case "quest":
                quest_id, _, sub = rest.partition(".")
                quest = state.quests.get(quest_id)
                if sub == "stage":
                    if quest is None or quest.status != "active":
                        return None
                    return self.title.quests[quest_id].stages[quest.stage].id
                return quest.status if quest else "inactive"
            case "location":
                return state.location
            case "global":
                return state.global_level
        match path:
            case "time.day":
                return state.day
            case "time.slot":
                return self.slots[state.slot]
            case "time.weekday":
                week = self.title.config.time.week or []
                return week[(state.day - 1) % len(week)] if week else None
        raise KeyError(path)

    def _holds(self, condition: dict[str, Any] | None, state: GameState) -> bool:
        return holds(condition, lambda path: self.read(state, path))

    # ── Что доступно игроку ───────────────────────────────────────────────

    def characters_at(self, state: GameState, location: str) -> list[str]:
        return [key for key in self.title.characters if self.where_is(state, key) == location]

    def where_is(self, state: GameState, character: str) -> str | None:
        slot = self.slots[state.slot]
        weekday = self.read(state, "time.weekday")
        for entry in self.title.characters[character].schedule:
            if entry.slots and slot not in entry.slots:
                continue
            if entry.weekdays and weekday not in entry.weekdays:
                continue
            if self._holds(entry.when, state):
                return entry.location
        return None

    def location_lock(self, state: GameState, key: str) -> str | None:
        """Почему в локацию нельзя пойти, или None."""
        location = self.title.locations[key]
        if not self._holds(location.visible_when, state):
            return "Локация ещё не открыта"
        if not self._holds(location.unlock_when, state):
            return location.locked_hint or "Пока закрыто"
        slot = self.slots[state.slot]
        if location.slots and slot not in location.slots:
            return f"Открыто: {self._slot_names(location.slots)}"
        return None

    def activity_lock(self, state: GameState, key: str) -> str | None:
        """Почему занятие недоступно, или None."""
        activity = self.title.activities[key]
        if state.location != activity.location:
            return "Нужно быть в этой локации"
        slot = self.slots[state.slot]
        location = self.title.locations[activity.location]
        if location.slots and slot not in location.slots:
            return f"Открыто: {self._slot_names(location.slots)}"
        if activity.slots and slot not in activity.slots:
            return f"Доступно: {self._slot_names(activity.slots)}"
        if (
            activity.with_character
            and self.where_is(state, activity.with_character) != state.location
        ):
            name = self.title.characters[activity.with_character].name
            return f"{name} сейчас не здесь"
        if not self._holds(activity.requires, state):
            return activity.locked_hint or "Пока недоступно"
        for resource, amount in activity.cost.resources.items():
            if self.read(state, f"resource.{resource}") < amount:
                name = self.title.config.resources[resource].name
                return f"Не хватает: {name.lower()} (нужно {amount})"
        return None

    def can_sleep(self, state: GameState) -> bool:
        allowed = self.title.config.time.sleep_from
        return not state.pending_scenes and (allowed is None or self.slots[state.slot] in allowed)

    def view(self, state: GameState, now: datetime) -> dict[str, Any]:
        """Всё, что нужно экрану: время, ресурсы, карта, занятия здесь, что можно сделать."""
        state = self.refresh(state, now)
        config = self.title.config
        resources: dict[str, Any] = {}
        for key, resource in config.resources.items():
            value = state.resources[key]
            next_at = None
            if resource.regen and value.anchor is not None:
                next_at = value.anchor + timedelta(minutes=resource.regen.every_minutes)
            resources[key] = {"value": value.value, "max": resource.max, "next_at": next_at}

        locations = []
        for key, location in self.title.locations.items():
            if not self._holds(location.visible_when, state):
                continue
            point = self.title.map.points.get(key)
            locations.append(
                {
                    "id": key,
                    "name": location.name,
                    "point": point.model_dump() if point else None,
                    "lock": self.location_lock(state, key),
                    "characters": self.characters_at(state, key),
                }
            )

        activities = []
        if state.location:
            for key, activity in self.title.activities.items():
                if activity.location == state.location:
                    activities.append(
                        {
                            "id": key,
                            "name": activity.name,
                            "cost": activity.cost.model_dump(),
                            "with_character": activity.with_character,
                            "lock": self.activity_lock(state, key),
                        }
                    )

        return {
            "state": state,
            "time": {
                "day": state.day,
                "slot": self.slots[state.slot],
                "weekday": self.read(state, "time.weekday"),
            },
            "resources": resources,
            "locations": locations,
            "here": {
                "location": state.location,
                "characters": self.characters_at(state, state.location) if state.location else [],
                "activities": activities,
            },
            "can_sleep": self.can_sleep(state),
            "pending_scene": state.pending_scenes[0].scene if state.pending_scenes else None,
        }

    # ── Действия ──────────────────────────────────────────────────────────

    def apply(self, state: GameState, action: Action, now: datetime) -> Outcome:
        before = self.refresh(state, now)
        outcome = Outcome(state=before.model_copy(deep=True))
        if outcome.state.finished:
            raise ActionError("finished", "Тайтл пройден")
        if outcome.state.pending_scenes and not isinstance(action, SceneComplete):
            raise ActionError("scene_pending", "Сначала досмотрите сцену")

        match action:
            case Go(location=location):
                self._go(outcome, location, now)
            case Leave():
                outcome.state.location = None
            case DoActivity(id=key):
                self._activity(outcome, key, now)
            case Gift(item=item, character=character):
                self._gift(outcome, item, character, now)
            case Use(item=item):
                self._use(outcome, item, now)
            case Sleep():
                if not self.can_sleep(outcome.state):
                    allowed = self._slot_names(self.title.config.time.sleep_from or [])
                    raise ActionError("cant_sleep", f"Лечь спать можно: {allowed}")
                self._new_day(outcome, now)
            case SceneComplete(scene=scene, effects=effects):
                self._scene_complete(outcome, scene, effects, now)

        self._check_quests(outcome, now)
        outcome.changes = self._diff(before, outcome.state)
        return outcome

    def _go(self, outcome: Outcome, key: str, now: datetime) -> None:
        if key not in self.title.locations:
            raise ActionError("unknown", f"Нет локации «{key}»")
        lock = self.location_lock(outcome.state, key)
        if lock:
            raise ActionError("locked", lock)
        outcome.state.location = key
        self._fire("enter", outcome, now, location=key)

    def _activity(self, outcome: Outcome, key: str, now: datetime) -> None:
        activity: Activity | None = self.title.activities.get(key)
        if activity is None:
            raise ActionError("unknown", f"Нет занятия «{key}»")
        lock = self.activity_lock(outcome.state, key)
        if lock:
            raise ActionError("locked", lock)
        for resource, amount in activity.cost.resources.items():
            self._add(outcome, f"resource.{resource}", -amount, now)
        self._apply(outcome, activity.effects, now)
        self._fire("activity", outcome, now, activity=key)
        self._advance(outcome, activity.cost.slots, now)

    def _gift(self, outcome: Outcome, item: str, character: str, now: datetime) -> None:
        state = outcome.state
        if self.title.items.get(item) is None or self.title.items[item].kind != "gift":
            raise ActionError("unknown", "Это нельзя подарить")
        if character not in self.title.characters:
            raise ActionError("unknown", f"Нет персонажа «{character}»")
        if state.items.get(item, 0) < 1:
            raise ActionError("no_item", "Этого предмета нет в инвентаре")
        if state.location is None or self.where_is(state, character) != state.location:
            raise ActionError(
                "not_here", f"{self.title.characters[character].name} сейчас не здесь"
            )
        limit = self.title.config.gifts.per_character_per_day
        if state.gifts_today.get(character, 0) >= limit:
            raise ActionError("gift_limit", "Сегодня подарков уже достаточно")
        state.gifts_today[character] = state.gifts_today.get(character, 0) + 1
        self._add(outcome, f"item.{item}", -1, now)
        delta = self.title.characters[character].gifts.get(
            item, self.title.config.gifts.default_affection
        )
        self._add(outcome, f"affection.{character}", delta, now)

    def _use(self, outcome: Outcome, item: str, now: datetime) -> None:
        definition = self.title.items.get(item)
        if definition is None or definition.kind != "consumable":
            raise ActionError("unknown", "Это нельзя использовать")
        if outcome.state.items.get(item, 0) < 1:
            raise ActionError("no_item", "Этого предмета нет в инвентаре")
        self._add(outcome, f"item.{item}", -1, now)
        self._apply(outcome, definition.use, now)

    def _scene_complete(
        self, outcome: Outcome, scene: str, raw: list[dict[str, Any]], now: datetime
    ) -> None:
        state = outcome.state
        if not state.pending_scenes or state.pending_scenes[0].scene != scene:
            raise ActionError("bad_scene", "Эта сцена сейчас не идёт")
        allowed = {
            json.dumps(effect, sort_keys=True) for effect in self.title.scenes[scene].effects
        }
        for effect in raw:
            if json.dumps(effect, sort_keys=True) not in allowed:
                raise ActionError("effect_not_allowed", f"Сцена не может дать эффект {effect}")
        state.pending_scenes.pop(0)
        self._apply(outcome, scene_effects_to_effects(raw), now)

    # ── Время, ресурсы, эффекты ──────────────────────────────────────────

    def _advance(self, outcome: Outcome, slots: int, now: datetime) -> None:
        outcome.state.slot += slots
        while outcome.state.slot >= len(self.slots) and not outcome.state.finished:
            outcome.state.slot -= len(self.slots)
            self._new_day(outcome, now, keep_slot=True)

    def _new_day(self, outcome: Outcome, now: datetime, keep_slot: bool = False) -> None:
        state = outcome.state
        state.day += 1
        if not keep_slot:
            state.slot = 0
        state.gifts_today = {}
        state.location = self.title.config.start.location
        outcome.new_day = True
        days = self.title.config.time.days
        if days is not None and state.day > days:
            state.finished = True
            return
        for key, resource in self.title.config.resources.items():
            if resource.on_new_day == "max" and resource.max is not None:
                missing = resource.max - state.resources[key].value
                self._add(outcome, f"resource.{key}", max(0, missing), now)
            elif isinstance(resource.on_new_day, int):
                self._add(outcome, f"resource.{key}", resource.on_new_day, now)
        self._fire("day_start", outcome, now)

    def _regen(self, state: GameState, now: datetime) -> None:
        for key, resource in self.title.config.resources.items():
            current = state.resources[key]
            if resource.regen is None or resource.max is None:
                continue
            if current.value >= resource.max:
                current.anchor = None
                continue
            if current.anchor is None:
                current.anchor = now
                continue
            every = timedelta(minutes=resource.regen.every_minutes)
            ticks = math.floor((now - current.anchor) / every)
            if ticks <= 0:
                continue
            current.value = min(resource.max, current.value + ticks * resource.regen.amount)
            current.anchor = (
                None if current.value >= resource.max else current.anchor + ticks * every
            )

    def _add(self, outcome: Outcome, path: str, amount: int, now: datetime) -> None:
        state = outcome.state
        config = self.title.config
        head, _, key = path.partition(".")
        match head:
            case "stat":
                stat = config.stats[key]
                state.stats[key] = max(stat.min, min(stat.max, state.stats.get(key, 0) + amount))
            case "resource":
                resource = config.resources[key]
                current = state.resources[key]
                was_full = resource.max is not None and current.value >= resource.max
                value = max(0, current.value + amount)
                if resource.max is not None:
                    value = min(resource.max, value)
                current.value = value
                if resource.regen and resource.max is not None:
                    if value >= resource.max:
                        current.anchor = None
                    elif was_full:
                        current.anchor = now
            case "affection":
                limits = config.affection
                value = state.affection.get(key, 0) + amount
                state.affection[key] = max(limits.min, min(limits.max, value))
            case "item":
                state.items[key] = max(0, state.items.get(key, 0) + amount)
            case "global":
                outcome.xp += amount

    def _apply(self, outcome: Outcome, effects: Effects, now: datetime) -> None:
        state = outcome.state
        for path, amount in effects.add.items():
            self._add(outcome, path, amount, now)
        for path, value in effects.set.items():
            state.flags[path.removeprefix("flag.")] = value
        for quest in effects.start_quest:
            self._start_quest(outcome, quest)
        for quest in effects.advance_quest:
            self._complete_stage(outcome, quest, now)
        for key in effects.achievement:
            if key not in state.achievements:
                state.achievements.append(key)
                outcome.achievements.append(key)

    # ── События и квесты ─────────────────────────────────────────────────

    def _fire(
        self,
        trigger: str,
        outcome: Outcome,
        now: datetime,
        activity: str | None = None,
        location: str | None = None,
    ) -> None:
        """Срабатывает одно событие с наивысшим приоритетом среди подходящих."""
        state = outcome.state
        candidates = [
            (key, event)
            for key, event in self.title.events.items()
            if event.trigger.on == trigger
            and (activity is None or event.trigger.activity == activity)
            and (location is None or event.trigger.location == location)
            and not (event.once and key in state.events_seen)
            and self._holds(event.when, state)
        ]
        if not candidates:
            return
        key, event = max(candidates, key=lambda pair: pair[1].priority)
        if key not in state.events_seen:
            state.events_seen.append(key)
        self._apply(outcome, event.effects, now)
        if event.scene:
            state.pending_scenes.append(PendingScene(scene=event.scene, event=key))
            outcome.scenes.append(event.scene)

    def _start_quest(self, outcome: Outcome, key: str) -> None:
        if key not in outcome.state.quests:
            outcome.state.quests[key] = QuestState(status="active")
            outcome.quests.append((key, "active", self.title.quests[key].stages[0].id))

    def _complete_stage(self, outcome: Outcome, key: str, now: datetime) -> None:
        quest = outcome.state.quests.get(key)
        if quest is None or quest.status != "active":
            return
        definition = self.title.quests[key]
        self._apply(outcome, definition.stages[quest.stage].effects, now)
        quest.stage += 1
        if quest.stage >= len(definition.stages):
            quest.status = "done"
            quest.stage = len(definition.stages) - 1
            outcome.quests.append((key, "done", None))
            self._apply(outcome, definition.rewards, now)
        else:
            outcome.quests.append((key, "active", definition.stages[quest.stage].id))

    def _check_quests(self, outcome: Outcome, now: datetime) -> None:
        """Стартует и продвигает квесты, пока что-то меняется."""
        state = outcome.state
        for _ in range(100):
            progressed = False
            for key, quest in self.title.quests.items():
                current = state.quests.get(key)
                if current is None:
                    if quest.start_when is not None and self._holds(quest.start_when, state):
                        self._start_quest(outcome, key)
                        progressed = True
                elif current.status == "active" and self._holds(
                    quest.stages[current.stage].complete_when, state
                ):
                    self._complete_stage(outcome, key, now)
                    progressed = True
            if not progressed:
                return

    # ── Вспомогательное ──────────────────────────────────────────────────

    def _slot_names(self, ids: list[str]) -> str:
        names = {slot.id: slot.name.lower() for slot in self.title.config.time.slots}
        return ", ".join(names.get(slot, slot) for slot in ids)

    @staticmethod
    def _diff(before: GameState, after: GameState) -> list[Change]:
        changes: list[Change] = []
        for head, old, new in (
            (
                "resource",
                {k: v.value for k, v in before.resources.items()},
                {k: v.value for k, v in after.resources.items()},
            ),
            ("stat", before.stats, after.stats),
            ("affection", before.affection, after.affection),
            ("item", before.items, after.items),
        ):
            for key in sorted(set(old) | set(new)):
                delta = new.get(key, 0) - old.get(key, 0)
                if delta:
                    changes.append(Change(f"{head}.{key}", delta))
        return changes
