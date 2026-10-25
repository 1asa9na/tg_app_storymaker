"""Данные тайтла: схемы Pydantic и проверка ссылок между сущностями.

Формат для геймдизайнера описан в docs/TITLE_FORMAT.md.
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


class Effects(Model):
    """Изменения состояния: начисления, флаги, квесты, достижения."""

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

    amount: int = Field(default=1, gt=0)
    every_minutes: float = Field(gt=0)


class Resource(Model):
    name: str
    start: int = 0
    max: int | None = None
    regen: Regen | None = None
    #: Сколько восстанавливается при смене игрового дня: число или "max".
    on_new_day: int | Literal["max"] | None = None

    @model_validator(mode="after")
    def _check(self) -> "Resource":
        if (self.regen or self.on_new_day == "max") and self.max is None:
            raise ValueError("для восстановления нужен max")
        return self


class Stat(Model):
    name: str
    start: int = 0
    min: int = 0
    max: int = 100


class Slot(Model):
    id: Id
    name: str


class Time(Model):
    slots: list[Slot] = Field(min_length=1)
    #: Слоты, из которых можно лечь спать; по умолчанию — из любого.
    sleep_from: IdList | None = None
    #: Длина тайтла в днях; после последнего дня игра заканчивается.
    days: int | None = Field(default=None, gt=0)
    #: Названия дней недели для расписаний (повторяются по кругу).
    week: list[str] | None = None


class Start(Model):
    location: Id | None = None
    items: dict[Id, int] = {}
    flags: IdList = []


class Gifts(Model):
    per_character_per_day: int = Field(default=1, ge=0)
    #: Симпатия за подарок, если у персонажа нет особого отношения к предмету.
    default_affection: int = 1


class Affection(Model):
    min: int = -100
    max: int = 100


class Config(Model):
    name: str
    time: Time
    resources: dict[Id, Resource] = {}
    stats: dict[Id, Stat] = {}
    start: Start = Start()
    gifts: Gifts = Gifts()
    affection: Affection = Affection()


class AffectionLevel(Model):
    at: int
    name: str


class ScheduleEntry(Model):
    location: Id
    slots: IdList | None = None
    weekdays: list[str] | None = None
    when: Condition | None = None


class Character(Model):
    name: str
    color: str | None = None
    emotions: IdList = Field(min_length=1)
    romance: bool = False
    affection_start: int = 0
    levels: list[AffectionLevel] = []
    #: Предмет → изменение симпатии за такой подарок.
    gifts: dict[Id, int] = {}
    #: Где персонаж бывает: первая подходящая запись выигрывает.
    schedule: list[ScheduleEntry] = []


class Point(Model):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class Map(Model):
    #: Ключ ассета с иллюстрацией карты; без неё карта — список карточек.
    image: Id | None = None
    points: dict[Id, Point] = {}


class Location(Model):
    name: str
    background: Id
    #: Слоты, когда локация открыта; по умолчанию — всегда.
    slots: IdList | None = None
    visible_when: Condition | None = None
    unlock_when: Condition | None = None
    locked_hint: str | None = None


class Cost(Model):
    """Цена занятия: слоты времени и ресурсы, например {slots: 1, energy: 20}."""

    model_config = ConfigDict(extra="allow", frozen=True)

    slots: int = Field(default=1, ge=0)

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
    name: str
    location: Id
    description: str = ""
    slots: IdList | None = None
    cost: Cost = Cost()
    requires: Condition | None = None
    locked_hint: str | None = None
    #: Занятие с персонажем: доступно, только когда он в этой локации.
    with_character: Id | None = None
    effects: Effects = Effects()


class Item(Model):
    name: str
    description: str = ""
    icon: Id | None = None
    kind: Literal["gift", "consumable", "key"] = "key"
    #: Эффекты использования расходника.
    use: Effects = Effects()


class QuestStage(Model):
    id: Id
    journal: str
    complete_when: Condition
    effects: Effects = Effects()


class Quest(Model):
    name: str
    #: Квест стартует сам, когда условие выполнено. Без условия — только эффектом start_quest.
    start_when: Condition | None = None
    stages: list[QuestStage] = Field(min_length=1)
    rewards: Effects = Effects()


class Trigger(Model):
    on: Literal["activity", "enter", "day_start"]
    activity: Id | None = None
    location: Id | None = None

    @model_validator(mode="after")
    def _check(self) -> "Trigger":
        if self.on == "activity" and self.activity is None:
            raise ValueError("для on: activity нужен activity")
        if self.on == "enter" and self.location is None:
            raise ValueError("для on: enter нужен location")
        return self


class Event(Model):
    trigger: Trigger
    when: Condition | None = None
    scene: Id | None = None
    effects: Effects = Effects()
    priority: int = 0
    once: bool = True

    @model_validator(mode="after")
    def _check(self) -> "Event":
        if self.scene is None and self.effects.is_empty():
            raise ValueError("событию нужна сцена или эффекты")
        return self


class Achievement(Model):
    name: str
    description: str = ""


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
