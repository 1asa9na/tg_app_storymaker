"""Симулятор баланса: виртуальные игроки проходят тайтл на том же движке, что и прод.

Игрок действует сессиями: играет, пока хватает энергии, потом «уходит» на session_gap часов,
а энергия тем временем восстанавливается в реальном времени. Отчёт показывает, сколько реального
времени занимает игровой день, как часто игроки упираются в энергию, какие сцены и квесты
до них доходят.
"""

import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from storymaker_api.game.engine import (
    Action,
    DoActivity,
    Engine,
    Gift,
    Go,
    SceneComplete,
    Sleep,
    Use,
)
from storymaker_api.game.schema import Title
from storymaker_api.game.state import GameState

START = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
#: Сколько реального времени занимает одно действие игрока.
ACTION_TIME = timedelta(minutes=1)


class Player(Protocol):
    def play(
        self, scene_json: str, snapshot: dict[str, Any], strategy: str, seed: int
    ) -> list[dict[str, Any]]: ...


@dataclass
class Settings:
    players: int = 100
    #: random — равномерно случайные занятия; romance:<персонаж> — упор на одного героя.
    strategy: str = "random"
    #: Выборы в сценах: free — без платных вариантов, random, first.
    scene_strategy: str = "free"
    #: Пауза между игровыми сессиями, часов.
    session_gap_hours: float = 4
    #: Сколько реального времени длится симуляция, часов.
    horizon_hours: float = 24 * 14
    seed: int = 1


@dataclass
class Run:
    day_reached_at: dict[int, float] = field(default_factory=dict)
    waits_by_day: Counter[int] = field(default_factory=Counter)
    scenes: set[str] = field(default_factory=set)
    quests_done_on: dict[str, int] = field(default_factory=dict)
    achievements: set[str] = field(default_factory=set)
    xp: int = 0
    final: GameState | None = None
    stuck: bool = False


def _snapshot(state: GameState) -> dict[str, Any]:
    return {
        "affection": state.affection,
        "items": state.items,
        "flags": state.flags,
        "stats": state.stats,
        "globalLevel": state.global_level,
    }


class Simulation:
    def __init__(self, title: Title, player: Player, settings: Settings) -> None:
        self.title = title
        self.engine = Engine(title)
        self.player = player
        self.settings = settings
        self.focus = (
            settings.strategy.removeprefix("romance:")
            if settings.strategy.startswith("romance:")
            else None
        )

    def run(self) -> list[Run]:
        return [self._play_one(index) for index in range(self.settings.players)]

    def _play_one(self, index: int) -> Run:
        rng = random.Random(self.settings.seed * 100_003 + index)
        run = Run()
        self._just_moved = False
        now = START
        horizon = START + timedelta(hours=self.settings.horizon_hours)
        state = self.engine.new_game(now)
        run.day_reached_at[1] = 0.0

        for _ in range(100_000):
            if state.finished or now >= horizon:
                break
            state = self.engine.refresh(state, now)
            action = self._next_action(state, rng)
            if action is None:
                if self._blocked_by_resources(state):
                    run.waits_by_day[state.day] += 1
                    now += timedelta(hours=self.settings.session_gap_hours)
                    continue
                run.stuck = True
                break
            if isinstance(action, SceneComplete):
                run.scenes.add(action.scene)
            outcome = self.engine.apply(state, action, now)
            state = outcome.state
            run.xp += outcome.xp
            run.achievements.update(outcome.achievements)
            for quest, status, _ in outcome.quests:
                if status == "done":
                    run.quests_done_on[quest] = state.day
            if outcome.new_day and state.day not in run.day_reached_at:
                run.day_reached_at[state.day] = (now - START) / timedelta(hours=1)
            now += ACTION_TIME
        run.final = state
        return run

    # ── Поведение игрока ────────────────────────────────────────────────

    def _next_action(self, state: GameState, rng: random.Random) -> Action | None:
        if state.pending_scenes:
            pending = state.pending_scenes[0]
            effects = self.player.play(
                self.title.scenes[pending.scene].json_,
                _snapshot(state),
                self.settings.scene_strategy,
                rng.randrange(1 << 30),
            )
            return SceneComplete(type="scene_complete", scene=pending.scene, effects=effects)

        gift = self._gift(state)
        if gift is not None:
            return gift

        # Варианты: занятие здесь или переход туда, где есть доступные занятия.
        options: list[tuple[Action, float]] = [
            (DoActivity(type="activity", id=key), 5.0 if self._is_focus(key) else 1.0)
            for key in self._affordable(state, state.location)
            if not self._idle(key)
        ]
        if not self._just_moved:
            for key in self.title.locations:
                if key == state.location or self.engine.location_lock(state, key) is not None:
                    continue
                if any(not self._idle(activity) for activity in self._affordable(state, key)):
                    weight = 5.0 if self._has_focus(state, key) else 1.0
                    options.append((Go(type="go", location=key), weight))
        if options:
            actions, weights = zip(*options, strict=True)
            choice = rng.choices(actions, weights=weights)[0]
            self._just_moved = isinstance(choice, Go)
            return choice

        drink = self._drink(state)
        if drink is not None:
            return drink
        if self._blocked_by_resources(state):
            # Энергия кончилась: игрок закрывает приложение и ждёт (это решает вызывающий код).
            return None
        if self.engine.can_sleep(state):
            return Sleep(type="sleep")
        # Делать нечего: пропустить время там, где это можно.
        idle = [key for key in self._affordable(state, state.location) if self._idle(key)]
        if idle:
            return DoActivity(type="activity", id=rng.choice(idle))
        for key in self.title.locations:
            if key == state.location or self.engine.location_lock(state, key) is not None:
                continue
            if any(self._idle(activity) for activity in self._affordable(state, key)):
                return Go(type="go", location=key)
        return None

    def _idle(self, activity: str) -> bool:
        """Занятие, которое только пропускает время."""
        definition = self.title.activities[activity]
        return definition.effects.is_empty() and not any(
            event.trigger.activity == activity for event in self.title.events.values()
        )

    def _affordable(self, state: GameState, location: str | None) -> list[str]:
        if location is None:
            return []
        probe = state.model_copy(update={"location": location})
        return [
            key
            for key, activity in self.title.activities.items()
            if activity.location == location and self.engine.activity_lock(probe, key) is None
        ]

    def _is_focus(self, activity: str) -> bool:
        if self.focus is None:
            return False
        definition = self.title.activities[activity]
        return definition.with_character == self.focus or (
            f"affection.{self.focus}" in definition.effects.add
        )

    def _has_focus(self, state: GameState, location: str) -> bool:
        return self.focus is not None and self.focus in self.engine.characters_at(state, location)

    def _gift(self, state: GameState) -> Gift | None:
        if state.location is None:
            return None
        limit = self.title.config.gifts.per_character_per_day
        for character in self.engine.characters_at(state, state.location):
            if state.gifts_today.get(character, 0) >= limit:
                continue
            liked = self.title.characters[character].gifts
            for item, count in state.items.items():
                definition = self.title.items.get(item)
                if (
                    count > 0
                    and definition
                    and definition.kind == "gift"
                    and liked.get(item, 0) > 0
                ):
                    return Gift(type="gift", item=item, character=character)
        return None

    def _drink(self, state: GameState) -> Use | None:
        for item, count in state.items.items():
            definition = self.title.items.get(item)
            if count > 0 and definition and definition.kind == "consumable":
                return Use(type="use", item=item)
        return None

    def _blocked_by_resources(self, state: GameState) -> bool:
        """Есть занятия, которые станут доступны, когда восстановятся ресурсы."""
        for location in self.title.locations:
            if self.engine.location_lock(state, location) is not None:
                continue
            probe = state.model_copy(update={"location": location})
            for key, activity in self.title.activities.items():
                if activity.location != location:
                    continue
                lock = self.engine.activity_lock(probe, key)
                if lock and lock.startswith("Не хватает"):
                    return True
        return False


# ── Отчёт ───────────────────────────────────────────────────────────────


def _median(values: list[float]) -> str:
    return f"{statistics.median(values):.1f}" if values else "—"


def _percent(part: int, total: int) -> str:
    return f"{100 * part / total:.0f}%" if total else "—"


def report(title: Title, settings: Settings, runs: list[Run]) -> str:
    total = len(runs)
    lines = [
        f"# Симуляция «{title.config.name}»",
        "",
        f"Игроков: {total}, стратегия: {settings.strategy}, выборы в сценах: "
        f"{settings.scene_strategy}, пауза между сессиями: {settings.session_gap_hours} ч, "
        f"горизонт: {settings.horizon_hours:.0f} ч.",
        "",
        "## Дни",
        "",
        "| День | Дошли | Медиана реальных часов до дня | Упоров в энергию на игрока |",
        "|---|---|---|---|",
    ]
    last = title.config.time.days
    days = sorted(
        {day for run in runs for day in run.day_reached_at if last is None or day <= last}
    )
    for day in days:
        reached = [run.day_reached_at[day] for run in runs if day in run.day_reached_at]
        waits = sum(run.waits_by_day[day] for run in runs) / total
        lines.append(
            f"| {day} | {_percent(len(reached), total)} | {_median(reached)} | {waits:.1f} |"
        )
    finished = sum(1 for run in runs if run.final and run.final.finished)
    stuck = sum(1 for run in runs if run.stuck)
    lines += ["", f"Прошли тайтл до конца: {_percent(finished, total)}."]
    if stuck:
        lines.append(
            f"Застряли без доступных действий: {_percent(stuck, total)} — это ошибка баланса."
        )

    lines += ["", "## Сцены", "", "| Сцена | Увидели |", "|---|---|"]
    for scene in title.scenes:
        seen = sum(1 for run in runs if scene in run.scenes)
        lines.append(f"| {scene} | {_percent(seen, total)} |")

    lines += [
        "",
        "## Квесты",
        "",
        "| Квест | Завершили | Медиана дня завершения |",
        "|---|---|---|",
    ]
    for quest in title.quests:
        days_done = [
            float(run.quests_done_on[quest]) for run in runs if quest in run.quests_done_on
        ]
        lines.append(f"| {quest} | {_percent(len(days_done), total)} | {_median(days_done)} |")

    lines += [
        "",
        "## Персонажи к концу",
        "",
        "| Персонаж | Медиана симпатии | Уровень |",
        "|---|---|---|",
    ]
    for key, character in title.characters.items():
        values = [float(run.final.affection.get(key, 0)) for run in runs if run.final]
        median = statistics.median(values) if values else 0
        level = next(
            (level.name for level in reversed(character.levels) if median >= level.at), "—"
        )
        lines.append(f"| {character.name} | {median:.0f} | {level} |")

    if title.config.stats:
        lines += ["", "## Характеристики к концу", "", "| Характеристика | Медиана |", "|---|---|"]
        for key, stat in title.config.stats.items():
            values = [float(run.final.stats.get(key, 0)) for run in runs if run.final]
            lines.append(f"| {stat.name} | {_median(values)} |")

    achievements: dict[str, int] = defaultdict(int)
    for run in runs:
        for key in run.achievements:
            achievements[key] += 1
    lines += [
        "",
        "## Глобальный прогресс",
        "",
        f"Медиана опыта аккаунта: {_median([float(run.xp) for run in runs])}.",
        "",
        "| Достижение | Получили |",
        "|---|---|",
    ]
    for key, achievement in title.achievements.items():
        lines.append(f"| {achievement.name} | {_percent(achievements[key], total)} |")
    return "\n".join(lines) + "\n"
