import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(Text)
    first_name: Mapped[str] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    language_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TitleRow(Base):
    """Тайтл в каталоге. Данные тайтла живут в сборке (пока — JSON в образе), здесь — ключ."""

    __tablename__ = "titles"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    sort: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Save(Base):
    __tablename__ = "saves"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    title_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("titles.id"), primary_key=True)
    #: main — игра; sandbox:<id> — песочница сотрудника (этап 3).
    slot: Mapped[str] = mapped_column(Text, primary_key=True, server_default="main")
    #: Хеш сборки тайтла, на которой сделано сохранение.
    build: Mapped[str] = mapped_column(Text)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ActionLog(Base):
    """Каждое принятое действие: защита от повторов, разбор жалоб, аналитика."""

    __tablename__ = "action_log"
    __table_args__ = (UniqueConstraint("user_id", "title_id", "slot", "request_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    title_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("titles.id"))
    slot: Mapped[str] = mapped_column(Text)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    #: Ревизия сохранения после действия.
    revision: Mapped[int] = mapped_column(Integer)
    action: Mapped[dict[str, Any]] = mapped_column(JSONB)
    #: Ответ клиенту: повторный запрос получает его же.
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AccountProgress(Base):
    __tablename__ = "account_progress"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    xp: Mapped[int] = mapped_column(BigInteger, server_default="0")
    level: Mapped[int] = mapped_column(Integer, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserAchievement(Base):
    __tablename__ = "user_achievements"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "title_id", "achievement_key", postgresql_nulls_not_distinct=True
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    #: None — достижение платформы.
    title_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("titles.id"))
    achievement_key: Mapped[str] = mapped_column(Text)
    unlocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
