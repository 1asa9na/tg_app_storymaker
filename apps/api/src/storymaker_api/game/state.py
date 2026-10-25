"""Сохранение игрока в тайтле. Хранится в базе как JSON, меняется только движком."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResourceState(_Model):
    value: int
    #: Момент, от которого отсчитывается следующее восстановление; None — ресурс полон.
    anchor: datetime | None = None


class QuestState(_Model):
    status: Literal["active", "done"]
    stage: int = 0


class PendingScene(_Model):
    scene: str
    event: str


class GameState(_Model):
    version: int = 1
    title: str
    day: int = 1
    slot: int = 0
    location: str | None = None
    resources: dict[str, ResourceState] = {}
    stats: dict[str, int] = {}
    affection: dict[str, int] = {}
    items: dict[str, int] = {}
    flags: dict[str, bool] = {}
    quests: dict[str, QuestState] = {}
    events_seen: list[str] = []
    achievements: list[str] = []
    gifts_today: dict[str, int] = {}
    #: Сцены, которые игрок должен досмотреть, по порядку.
    pending_scenes: list[PendingScene] = []
    #: Уровень аккаунта: его подставляет платформа, тайтл только читает.
    global_level: int = 1
    finished: bool = False
