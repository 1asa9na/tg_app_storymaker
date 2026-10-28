"""Данные тайтла: схемы Pydantic и проверка ссылок между сущностями.

Формат для геймдизайнера описан в docs/TITLE_FORMAT.md. Из этих же схем студия строит формы
(JSON Schema): title — подпись поля, x-ref — на какой раздел ссылается значение (выпадающий
список), x-key-ref — то же для ключей словаря, x-yaml — свободная структура, редактируется
YAML-блоком (условия и эффекты).
"""

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

Id = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]


def _as_list(value: Any) -> Any:
    return [value] if isinstance(value, str) else value


IdList = Annotated[list[Id], BeforeValidator(_as_list)]

#: Условие — словарь «путь → значение или операторы», см. conditions.py.
Condition = dict[str, Any]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def F(
    title: str,
    default: Any = ...,
    *,
    ref: str | None = None,
    key_ref: str | None = None,
    yaml: bool = False,
    hint: str | None = None,
    **constraints: Any,
) -> Any:
    """Поле с подписью и подсказками для формы студии."""
    extra: dict[str, Any] = {}
    if ref:
        extra["x-ref"] = ref
    if key_ref:
        extra["x-key-ref"] = key_ref
    if yaml:
        extra["x-yaml"] = True
    return Field(
        default, title=title, description=hint, json_schema_extra=extra or None, **constraints
    )


class Effects(Model):
    """Изменения состояния: начисления, флаги, квесты, достижения."""

    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_extra={"x-yaml": True})

    add: dict[str, int] = {}
    set: dict[str, bool] = {}
    start_quest: IdList = []
    advance_quest: IdList = []
    achievement: IdList = []

    def is_empty(self) -> bool:
        return not (
            self.add or self.set or self.start_quest or self.advance_quest or self.achievement
        )


class Regen(Model):
    """Восстановление в реальном времени: +amount каждые every_minutes, до максимума."""

    amount: int = F("Сколько", 1, gt=0)
    every_minutes: float = F("Раз в сколько минут", gt=0)


class Resource(Model):
    name: str = F("Название")
    start: int = F("В начале", 0)
    max: int | None = F("Максимум", None)
    regen: Regen | None = F("Восстановление в реальном времени", None)
    #: Сколько восстанавливается при смене игрового дня: число или "max".
    on_new_day: int | Literal["max"] | None = F(
        "При смене дня", None, hint="Сколько прибавить утром: число или max"
    )

    @model_validator(mode="after")
    def _check(self) -> "Resource":
        if (self.regen or self.on_new_day == "max") and self.max is None:
            raise ValueError("для восстановления нужен max")
        return self


class Stat(Model):
    name: str = F("Название")
    start: int = F("В начале", 0)
    min: int = F("Минимум", 0)
    max: int = F("Максимум", 100)


class Slot(Model):
    id: Id = F("Ключ")
    name: str = F("Название")


class Time(Model):
    slots: list[Slot] = F("Части дня", min_length=1)
    #: Слоты, из которых можно лечь спать; по умолчанию — из любого.
    sleep_from: IdList | None = F("Лечь спать можно", None, ref="slots", hint="Пусто — всегда")
    #: Длина тайтла в днях; после последнего дня игра заканчивается.
    days: int | None = F("Дней в тайтле", None, gt=0, hint="Пусто — без конца")
    #: Названия дней недели для расписаний (повторяются по кругу).
    week: list[str] | None = F("Дни недели", None, hint="Через запятую: пн, вт, ср…")


class Start(Model):
    location: Id | None = F("Где начинает и просыпается", None, ref="locations")
    items: dict[Id, int] = F("Предметы в начале", {}, key_ref="items")
    flags: IdList = F("Флаги в начале", [])


class Gifts(Model):
    per_character_per_day: int = F("Подарков персонажу в день", 1, ge=0)
    #: Симпатия за подарок, если у персонажа нет особого отношения к предмету.
    default_affection: int = F("Симпатия за обычный подарок", 1)


class Affection(Model):
    min: int = F("Минимум", -100)
    max: int = F("Максимум", 100)


class Config(Model):
    name: str = F("Название тайтла")
    time: Time = F("Время")
    resources: dict[Id, Resource] = F("Ресурсы", {})
    stats: dict[Id, Stat] = F("Характеристики", {})
    start: Start = F("Старт", Start())
    gifts: Gifts = F("Подарки", Gifts())
    affection: Affection = F("Границы симпатии", Affection())


class AffectionLevel(Model):
    at: int = F("С симпатии")
    name: str = F("Название")


class ScheduleEntry(Model):
    location: Id = F("Где", ref="locations")
    slots: IdList | None = F("Когда", None, ref="slots", hint="Пусто — в любое время")
    weekdays: list[str] | None = F("Дни недели", None, ref="weekdays", hint="Пусто — каждый день")
    when: Condition | None = F("Условие", None, yaml=True)


class Character(Model):
    name: str = F("Имя")
    color: str | None = F("Цвет имени", None, hint="Например #f19bb8")
    emotions: IdList = F("Эмоции", min_length=1, hint="Через запятую: neutral, happy, smirk")
    romance: bool = F("Романтическая линия", False)
    affection_start: int = F("Симпатия в начале", 0)
    levels: list[AffectionLevel] = F("Уровни отношений", [])
    #: Предмет → изменение симпатии за такой подарок.
    gifts: dict[Id, int] = F("Отношение к подаркам", {}, key_ref="items")
    #: Где персонаж бывает: первая подходящая запись выигрывает.
    schedule: list[ScheduleEntry] = F(
        "Расписание", [], hint="Сверху вниз: первая подходящая запись выигрывает"
    )


class Point(Model):
    x: float = F("x (0–1)", ge=0, le=1)
    y: float = F("y (0–1)", ge=0, le=1)


class Map(Model):
    #: Ключ ассета с иллюстрацией карты; без неё карта — список карточек.
    image: Id | None = F("Картинка карты", None, hint="Ключ ассета map_<ключ>; пусто — карточки")
    points: dict[Id, Point] = F("Точки локаций", {}, key_ref="locations")


class Location(Model):
    name: str = F("Название")
    background: Id = F("Фон", hint="Ключ ассета bg_<ключ>")
    #: Слоты, когда локация открыта; по умолчанию — всегда.
    slots: IdList | None = F("Открыта", None, ref="slots", hint="Пусто — всегда")
    visible_when: Condition | None = F("Видна на карте, когда", None, yaml=True)
    unlock_when: Condition | None = F("Открывается, когда", None, yaml=True)
    locked_hint: str | None = F("Подсказка, пока закрыта", None)


class Cost(Model):
    """Цена занятия: слоты времени и ресурсы, например {slots: 1, energy: 20}."""

    model_config = ConfigDict(extra="allow", frozen=True, json_schema_extra={"x-cost": True})

    slots: int = F("Частей дня", 1, ge=0)

    @property
    def resources(self) -> dict[str, int]:
        return {key: int(value) for key, value in (self.model_extra or {}).items()}

    @model_validator(mode="after")
    def _check(self) -> "Cost":
        for key, value in (self.model_extra or {}).items():
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"цена {key}: ожидается неотрицательное целое число")
        return self


class Activity(Model):
    name: str = F("Название")
    location: Id = F("Локация", ref="locations")
    description: str = F("Описание", "")
    slots: IdList | None = F(
        "Когда доступно", None, ref="slots", hint="Пусто — когда открыта локация"
    )
    cost: Cost = F("Цена", Cost())
    requires: Condition | None = F("Требует", None, yaml=True)
    locked_hint: str | None = F("Подсказка, пока недоступно", None)
    #: Занятие с персонажем: доступно, только когда он в этой локации.
    with_character: Id | None = F("С персонажем", None, ref="characters")
    effects: Effects = F("Что даёт", Effects())


class Item(Model):
    name: str = F("Название")
    description: str = F("Описание", "")
    icon: Id | None = F("Иконка", None, hint="Ключ ассета, например item_rose")
    kind: Literal["gift", "consumable", "key"] = F(
        "Вид", "key", hint="gift — подарок, consumable — расходник, key — сюжетный"
    )
    #: Эффекты использования расходника.
    use: Effects = F("Что даёт при использовании", Effects())


class QuestStage(Model):
    id: Id = F("Ключ этапа")
    journal: str = F("Текст в журнале")
    complete_when: Condition = F("Выполнен, когда", yaml=True)
    effects: Effects = F("Награда за этап", Effects())


class Quest(Model):
    name: str = F("Название")
    #: Квест стартует сам, когда условие выполнено. Без условия — только эффектом start_quest.
    start_when: Condition | None = F(
        "Начинается, когда", None, yaml=True, hint="Пусто — только эффектом start_quest"
    )
    stages: list[QuestStage] = F("Этапы", min_length=1)
    rewards: Effects = F("Награда за квест", Effects())


def normalize_trigger(value: Any) -> Any:
    """Короткая запись: day_start | {activity: <занятие>} | {enter: <локация>}."""
    if value == "day_start":
        return {"on": "day_start"}
    if isinstance(value, dict) and len(value) == 1:
        ((key, target),) = value.items()
        if key == "activity":
            return {"on": "activity", "activity": target}
        if key == "enter":
            return {"on": "enter", "location": target}
    return value


class Trigger(Model):
    on: Literal["activity", "enter", "day_start"] = F(
        "Когда проверяется", hint="activity — после занятия, enter — при входе, day_start — утром"
    )
    activity: Id | None = F("Занятие", None, ref="activities")
    location: Id | None = F("Локация", None, ref="locations")

    @model_validator(mode="after")
    def _check(self) -> "Trigger":
        if self.on == "activity" and self.activity is None:
            raise ValueError("для on: activity нужен activity")
        if self.on == "enter" and self.location is None:
            raise ValueError("для on: enter нужен location")
        return self


TriggerField = Annotated[Trigger, BeforeValidator(normalize_trigger)]


class Event(Model):
    #: day_start, {activity: <занятие>} или {enter: <локация>}.
    trigger: TriggerField = F("Триггер")
    when: Condition | None = F("Условие", None, yaml=True)
    scene: Id | None = F("Сцена", None, ref="scenes")
    effects: Effects = F("Эффекты", Effects())
    priority: int = F("Приоритет", 0, hint="Из подходящих срабатывает с наибольшим")
    once: bool = F("Один раз", True)

    @model_validator(mode="after")
    def _check(self) -> "Event":
        if self.scene is None and self.effects.is_empty():
            raise ValueError("событию нужна сцена или эффекты")
        return self


class Achievement(Model):
    name: str = F("Название")
    description: str = F("Описание", "")


class Scene(Model):
    """Скомпилированная сцена: JSON для inkjs и белый список эффектов."""

    json_: str = Field(alias="json")
    effects: list[dict[str, Any]] = []


class Title(Model):
    id: Id
    config: Config
    characters: dict[Id, Character] = {}
    map: Map = Map()
    locations: dict[Id, Location] = {}
    activities: dict[Id, Activity] = {}
    items: dict[Id, Item] = {}
    quests: dict[Id, Quest] = {}
    events: dict[Id, Event] = {}
    achievements: dict[Id, Achievement] = {}
    scenes: dict[Id, Scene] = {}

    @property
    def slot_ids(self) -> list[str]:
        return [slot.id for slot in self.config.time.slots]
