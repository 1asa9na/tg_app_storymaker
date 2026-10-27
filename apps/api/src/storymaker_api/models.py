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
    #: draft — виден только в студии; published — в каталоге; hidden — снят, сохранения живы.
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    #: Сборка, которую играют игроки.
    active_build_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("builds.id", use_alter=True, name="titles_active_build_id_fkey")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TitleDocument(Base):
    """Сущность тайтла: персонаж, локация, занятие… Раздел config и карта — ключ main."""

    __tablename__ = "title_documents"
    __table_args__ = (UniqueConstraint("title_id", "kind", "key"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    title_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("titles.id"))
    #: Раздел тайтла: config, characters, map, locations, activities, items, quests, events,
    #: achievements.
    kind: Mapped[str] = mapped_column(Text)
    key: Mapped[str] = mapped_column(Text)
    data: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SceneSource(Base):
    __tablename__ = "scenes"
    __table_args__ = (UniqueConstraint("title_id", "key"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    title_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("titles.id"))
    key: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Build(Base):
    """Собранный тайтл: проверенные данные и скомпилированные сцены. Не меняется после сборки."""

    __tablename__ = "builds"
    __table_args__ = (UniqueConstraint("title_id", "version"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    title_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("titles.id"))
    version: Mapped[int] = mapped_column(Integer)
    #: Хеш данных: по нему сохранение замечает, что тайтл обновился.
    hash: Mapped[str] = mapped_column(Text)
    #: Title целиком (dump_title), сцены уже скомпилированы.
    data: Mapped[str] = mapped_column(Text)
    warnings: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    #: Ассеты на момент сборки: вид → ключ → адреса вариантов (assets.build_manifest).
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    notes: Mapped[str] = mapped_column(Text, server_default="")
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Asset(Base):
    """Ассет тайтла по ключу: фон gym, спрайт anna_smirk, музыка calm. Файлы — в версиях."""

    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("title_id", "kind", "key"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    title_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("titles.id"))
    kind: Mapped[str] = mapped_column(Text)
    key: Mapped[str] = mapped_column(Text)
    current_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("asset_versions.id", use_alter=True, name="assets_current_version_id_fkey"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssetVersion(Base):
    """Загруженный исходник и его варианты. Не меняется и не удаляется."""

    __tablename__ = "asset_versions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("assets.id"))
    #: Ключ исходника в бакете originals.
    original_key: Mapped[str] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(Integer)
    #: Имя варианта → путь внутри /assets: {"1080": "t/demo/3f/3fa9….1080.webp", …}.
    variants: Mapped[dict[str, str]] = mapped_column(JSONB)
    warnings: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Staff(Base):
    """Команда: кто может войти в студию и что там делать."""

    __tablename__ = "staff"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    #: admin — всё; designer — данные, сборка, публикация; writer — сцены.
    role: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LoginToken(Base):
    """Одноразовая ссылка входа в студию из бота. Хранится только хеш."""

    __tablename__ = "login_tokens"

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StudioSession(Base):
    __tablename__ = "studio_sessions"

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
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
