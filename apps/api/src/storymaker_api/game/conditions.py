"""Условия и пути к состоянию игры.

Условие — словарь «путь → значение» или «путь → {оператор: значение}»:

    affection.anna: {gte: 10}
    flag.met_anna: true
    time.slot: evening
    any: [{item.rose: {gte: 1}}, {flag.has_flowers: true}]
    not: {quest.anna_coffee: done}

Все условия словаря должны выполняться одновременно.
"""

from collections.abc import Callable
from typing import Any

from storymaker_api.game.schema import Condition, Effects, Title

NUMBER_OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "in"}
EQUALITY_OPS = {"eq", "ne", "in"}
QUEST_STATUSES = ("inactive", "active", "done")
COMBINATORS = {"any", "all", "not"}

Reader = Callable[[str], Any]


_REGISTRIES: dict[str, tuple[str, Callable[[Title], dict[str, Any]]]] = {
    "stat": ("характеристики", lambda title: title.config.stats),
    "resource": ("ресурса", lambda title: title.config.resources),
    "affection": ("персонажа", lambda title: title.characters),
    "item": ("предмета", lambda title: title.items),
    "event": ("события", lambda title: title.events),
}


def _kind(path: str, title: Title) -> tuple[str, list[str] | None] | str:
    """Тип значения по пути: ("number"|"bool"|"enum", допустимые значения) или текст ошибки."""
    head, _, rest = path.partition(".")
    if head in _REGISTRIES or head == "flag":
        if not rest or "." in rest:
            return f"неизвестный путь «{path}»"
        if head in _REGISTRIES:
            noun, registry = _REGISTRIES[head]
            if rest not in registry(title):
                return f"{noun} «{rest}» нет в тайтле"
        return ("bool", None) if head in ("flag", "event") else ("number", None)
    if head == "quest" and rest:
        quest_id, _, sub = rest.partition(".")
        quest = title.quests.get(quest_id)
        if quest is None:
            return f"квеста «{quest_id}» нет в тайтле"
        if sub == "":
            return ("enum", list(QUEST_STATUSES))
        if sub == "stage":
            return ("enum", [stage.id for stage in quest.stages])
        return f"неизвестный путь «{path}»"
    match path:
        case "time.day" | "global.level":
            return ("number", None)
        case "time.slot":
            return ("enum", title.slot_ids)
        case "time.weekday":
            week = title.config.time.week
            return ("enum", week) if week else "в title.yaml не задана неделя (time.week)"
        case "location":
            return ("enum", list(title.locations))
    return f"неизвестный путь «{path}»"


def check_condition(condition: Condition | None, title: Title, where: str) -> list[str]:
    """Ошибки в условии: неизвестные пути, ключи, операторы и типы значений."""
    if condition is None:
        return []
    if not isinstance(condition, dict) or not condition:
        return [f"{where}: условие должно быть непустым словарём"]
    errors: list[str] = []
    for path, expected in condition.items():
        if path in ("any", "all"):
            if not isinstance(expected, list) or not expected:
                errors.append(f"{where}.{path}: ожидается непустой список условий")
                continue
            for index, item in enumerate(expected):
                errors += check_condition(item, title, f"{where}.{path}[{index}]")
            continue
        if path == "not":
            errors += check_condition(expected, title, f"{where}.not")
            continue
        kind = _kind(path, title)
        if isinstance(kind, str):
            errors.append(f"{where}.{path}: {kind}")
            continue
        errors += _check_value(kind, expected, f"{where}.{path}")
    return errors


def _check_value(kind: tuple[str, list[str] | None], expected: Any, where: str) -> list[str]:
    value_kind, allowed = kind
    ops = expected if isinstance(expected, dict) else {"eq": expected}
    errors: list[str] = []
    for op, value in ops.items():
        valid_ops = NUMBER_OPS if value_kind == "number" else EQUALITY_OPS
        if op not in valid_ops:
            errors.append(
                f"{where}: оператор «{op}» не подходит, можно: {', '.join(sorted(valid_ops))}"
            )
            continue
        values = value if op == "in" else [value]
        if op == "in" and not isinstance(value, list):
            errors.append(f"{where}: для in нужен список")
            continue
        for item in values:
            if value_kind == "number" and (not isinstance(item, int) or isinstance(item, bool)):
                errors.append(f"{where}: ожидается целое число, получено {item!r}")
            elif value_kind == "bool" and not isinstance(item, bool):
                errors.append(f"{where}: ожидается true или false, получено {item!r}")
            elif value_kind == "enum" and allowed is not None and item not in allowed:
                errors.append(
                    f"{where}: «{item}» — нет такого значения, можно: {', '.join(allowed)}"
                )
    return errors


ADDABLE = {"stat", "resource", "affection", "item"}


def check_effects(effects: Effects, title: Title, where: str) -> list[str]:
    errors: list[str] = []
    for path in effects.add:
        head, _, key = path.partition(".")
        if path == "global.xp":
            continue
        if head not in ADDABLE or not key:
            errors.append(
                f"{where}.add.{path}: начислять можно stat, resource, affection, item, global.xp"
            )
            continue
        kind = _kind(path, title)
        if isinstance(kind, str):
            errors.append(f"{where}.add.{path}: {kind}")
    for path in effects.set:
        head, _, key = path.partition(".")
        if head != "flag" or not key or "." in key:
            errors.append(f"{where}.set.{path}: устанавливать можно только flag.<имя>")
    for field in ("start_quest", "advance_quest"):
        for quest in getattr(effects, field):
            if quest not in title.quests:
                errors.append(f"{where}.{field}: квеста «{quest}» нет в тайтле")
    for key in effects.achievement:
        if key not in title.achievements:
            errors.append(f"{where}.achievement: достижения «{key}» нет в тайтле")
    return errors


def holds(condition: Condition | None, read: Reader) -> bool:
    """Выполняется ли условие. Условие уже проверено check_condition."""
    if condition is None:
        return True
    for path, expected in condition.items():
        if path == "any":
            if not any(holds(item, read) for item in expected):
                return False
            continue
        if path == "all":
            if not all(holds(item, read) for item in expected):
                return False
            continue
        if path == "not":
            if holds(expected, read):
                return False
            continue
        actual = read(path)
        ops = expected if isinstance(expected, dict) else {"eq": expected}
        if not all(_compare(op, actual, value) for op, value in ops.items()):
            return False
    return True


def _compare(op: str, actual: Any, value: Any) -> bool:
    match op:
        case "eq":
            return actual == value
        case "ne":
            return actual != value
        case "in":
            return actual in value
        case "gt":
            return actual > value
        case "gte":
            return actual >= value
        case "lt":
            return actual < value
        case "lte":
            return actual <= value
    raise ValueError(op)
