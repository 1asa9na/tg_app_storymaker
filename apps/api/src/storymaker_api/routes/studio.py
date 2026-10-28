"""API студии: вход, тайтлы, импорт и экспорт, сборки, публикация.

Вход — cookie-сессия (studio/auth.py), не initData: студия — сайт, а не Mini App.
"""

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api import documents, play
from storymaker_api.assets import (
    LABELS,
    MAX_BYTES,
    AssetError,
    Kind,
    Storage,
    file_name,
    referenced,
)
from storymaker_api.catalog import Catalog
from storymaker_api.config import Settings, get_settings
from storymaker_api.content import (
    create_build,
    current_assets,
    export_zip,
    get_or_create_title,
    import_files,
    load_content,
    publish,
    upload_asset,
)
from storymaker_api.db import get_session
from storymaker_api.game.scenes import EngineUnavailableError
from storymaker_api.game.schema import Id
from storymaker_api.game.simulator import Settings as SimulationSettings
from storymaker_api.game.simulator import parse_goal
from storymaker_api.models import (
    Asset,
    AssetVersion,
    Build,
    SceneSource,
    TitleDocument,
    TitleRow,
    User,
)
from storymaker_api.routes.game import game_routes
from storymaker_api.studio.auth import (
    COOKIE,
    SESSION_TTL,
    Member,
    current_member,
    end_session,
    exchange_login_token,
    require,
    staff_role,
)
from storymaker_api.studio.sandbox import MAX_PLAYERS, create_preview_token, simulate

router = APIRouter(prefix="/api/studio")

SessionDep = Annotated[AsyncSession, Depends(get_session)]
MemberDep = Annotated[Member, Depends(current_member)]
EditorDep = Annotated[Member, Depends(require("designer"))]

#: Предел для импорта: тайтл — это тексты, мегабайты здесь — ошибка.
MAX_FILES = 300
MAX_TOTAL = 5_000_000


def _member(member: Member) -> dict[str, Any]:
    return {
        "id": member.user.id,
        "first_name": member.user.first_name,
        "username": member.user.username,
        "role": member.role,
    }


# ── Вход ────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)


@router.post("/login")
async def login(
    body: LoginRequest,
    response: Response,
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Одноразовая ссылка из бота → cookie-сессия на 30 дней."""
    exchanged = await exchange_login_token(session, body.token, datetime.now(UTC))
    if exchanged is None:
        await session.commit()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Ссылка недействительна или устарела. Отправьте боту /studio ещё раз.",
        )
    token, user = exchanged
    role = await staff_role(session, user.id)
    assert role is not None
    await session.commit()
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        path="/api/studio",
        httponly=True,
        secure=settings.app_env != "local",
        samesite="lax",
    )
    return _member(Member(user, role))


@router.post("/logout")
async def logout(
    response: Response,
    session: SessionDep,
    member: MemberDep,
    token: Annotated[str, Cookie(alias=COOKIE)],
) -> dict[str, bool]:
    del member
    await end_session(session, token)
    await session.commit()
    response.delete_cookie(COOKIE, path="/api/studio")
    return {"ok": True}


@router.get("/me")
async def me(member: MemberDep) -> dict[str, Any]:
    return _member(member)


# ── Тайтлы ──────────────────────────────────────────────────────────────


async def _title(session: AsyncSession, slug: str) -> TitleRow:
    title = await session.scalar(select(TitleRow).where(TitleRow.slug == slug))
    if title is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "title not found")
    return title


def _build(build: Build, active_id: int | None, authors: dict[int, str]) -> dict[str, Any]:
    return {
        "id": build.id,
        "version": build.version,
        "hash": build.hash,
        "notes": build.notes,
        "warnings": build.warnings,
        "created_at": build.created_at,
        "created_by": authors.get(build.created_by) if build.created_by else None,
        "active": build.id == active_id,
    }


@router.get("/titles")
async def titles(session: SessionDep, member: MemberDep) -> list[dict[str, Any]]:
    del member
    rows = list(await session.scalars(select(TitleRow).order_by(TitleRow.sort, TitleRow.id)))
    versions = dict(
        (
            await session.execute(
                select(Build.title_id, func.max(Build.version)).group_by(Build.title_id)
            )
        ).all()
    )
    active = dict(
        (
            await session.execute(
                select(Build.id, Build.version).where(
                    Build.id.in_([r.active_build_id for r in rows if r.active_build_id])
                )
            )
        ).all()
    )
    documents = dict(
        (
            await session.execute(
                select(TitleDocument.title_id, func.max(TitleDocument.updated_at)).group_by(
                    TitleDocument.title_id
                )
            )
        ).all()
    )
    return [
        {
            "slug": row.slug,
            "name": row.name,
            "status": row.status,
            "active_version": active.get(row.active_build_id) if row.active_build_id else None,
            "latest_version": versions.get(row.id),
            "updated_at": documents.get(row.id),
        }
        for row in rows
    ]


@router.get("/titles/{slug}")
async def title(slug: str, session: SessionDep, member: MemberDep) -> dict[str, Any]:
    del member
    row = await _title(session, slug)
    builds = list(
        await session.scalars(
            select(Build).where(Build.title_id == row.id).order_by(Build.version.desc()).limit(30)
        )
    )
    author_ids = {build.created_by for build in builds if build.created_by}
    authors = dict(
        (
            await session.execute(select(User.id, User.first_name).where(User.id.in_(author_ids)))
        ).all()
    )
    counts = dict(
        (
            await session.execute(
                select(TitleDocument.kind, func.count())
                .where(TitleDocument.title_id == row.id)
                .group_by(TitleDocument.kind)
            )
        ).all()
    )
    scenes = await session.scalar(
        select(func.count()).select_from(SceneSource).where(SceneSource.title_id == row.id)
    )
    return {
        "slug": row.slug,
        "name": row.name,
        "status": row.status,
        "documents": counts,
        "scenes": scenes or 0,
        "builds": [_build(build, row.active_build_id, authors) for build in builds],
    }


class ImportRequest(BaseModel):
    #: Путь внутри папки тайтла → текст: «title.yaml», «scenes/intro.ink».
    files: dict[str, str]


@router.post("/titles/{slug}/import")
async def import_title(
    slug: Id, body: ImportRequest, session: SessionDep, member: EditorDep
) -> dict[str, Any]:
    """Заменяет данные и сцены тайтла файлами из папки геймдизайнера. Новый slug — новый тайтл."""
    if len(body.files) > MAX_FILES or sum(len(text) for text in body.files.values()) > MAX_TOTAL:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "too many files")
    row = await get_or_create_title(session, slug, slug)
    errors = await import_files(session, row, body.files, member.user.id)
    if errors:
        await session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"errors": errors})
    await session.commit()
    return {"slug": row.slug, "name": row.name}


@router.get("/titles/{slug}/export")
async def export_title(slug: str, session: SessionDep, member: MemberDep) -> Response:
    del member
    row = await _title(session, slug)
    archive = export_zip(row.slug, await load_content(session, row.id))
    return Response(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{row.slug}.zip"'},
    )


class BuildRequest(BaseModel):
    notes: str = Field(default="", max_length=2000)


@router.post("/titles/{slug}/builds")
async def build_title(
    slug: str, body: BuildRequest, session: SessionDep, member: EditorDep
) -> dict[str, Any]:
    """Собирает тайтл: схемы, ссылки, сцены. С ошибками сборка не сохраняется — 422."""
    row = await _title(session, slug)
    result = await create_build(session, row, member.user.id, body.notes)
    if result.build is None:
        await session.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"errors": result.errors, "warnings": result.warnings},
        )
    await session.commit()
    return _build(result.build, row.active_build_id, {member.user.id: member.user.first_name})


class PublishRequest(BaseModel):
    build_id: int
    #: Опубликовать, даже если сборка теряет ключи, на которые ссылаются сохранения.
    force: bool = False


@router.post("/titles/{slug}/publish")
async def publish_title(
    slug: str, body: PublishRequest, session: SessionDep, member: EditorDep
) -> dict[str, Any]:
    """Делает сборку активной: игроки получают её со следующего запроса. Это же — откат."""
    row = await _title(session, slug)
    build = await session.get(Build, body.build_id)
    if build is None or build.title_id != row.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "build not found")
    if body.force and member.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "force publish is admin only")
    lost = await publish(session, row, build, force=body.force)
    if lost:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "lost_ids", "lost": lost})
    await session.commit()
    return {"slug": row.slug, "active_version": build.version, "status": row.status}


class StatusRequest(BaseModel):
    status: Literal["published", "hidden"]


@router.post("/titles/{slug}/status")
async def title_status(
    slug: str, body: StatusRequest, session: SessionDep, member: EditorDep
) -> dict[str, Any]:
    """Скрыть тайтл из каталога или вернуть. Сохранения игроков не трогаются."""
    del member
    row = await _title(session, slug)
    if body.status == "published" and row.active_build_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "no_build"})
    row.status = body.status
    await session.commit()
    return {"slug": row.slug, "status": row.status}


# ── Ассеты ──────────────────────────────────────────────────────────────


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


@router.post("/titles/{slug}/assets")
async def upload(
    slug: str,
    file: UploadFile,
    session: SessionDep,
    member: EditorDep,
    storage: Annotated[Storage, Depends(get_storage)],
) -> dict[str, Any]:
    """Один файл от художника. Вид и ключ — из имени: bg_gym.png, anna_smirk.png (ASSETS.md)."""
    row = await _title(session, slug)
    data = await file.read(MAX_BYTES + 1)
    filename = file.filename or ""
    try:
        uploaded = await upload_asset(session, storage, row, filename, data, member.user.id)
    except AssetError as error:
        await session.rollback()
        message = str(error) if str(error).startswith(filename) else f"{filename}: {error}"
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"errors": [message]}) from None
    await session.commit()
    return {
        "kind": uploaded.asset.kind,
        "key": uploaded.asset.key,
        "unchanged": uploaded.unchanged,
        "warnings": uploaded.version.warnings,
    }


@router.get("/titles/{slug}/assets")
async def assets(slug: str, session: SessionDep, member: MemberDep) -> dict[str, Any]:
    """Ассеты тайтла, каких не хватает данным и сценам и какие ни к чему не привязаны."""
    del member
    row = await _title(session, slug)
    versions = await session.execute(
        select(Asset.kind, Asset.key, AssetVersion)
        .join(AssetVersion, AssetVersion.id == Asset.current_version_id)
        .where(Asset.title_id == row.id)
        .order_by(Asset.kind, Asset.key)
    )
    content = await load_content(session, row.id)
    needed = referenced(content.sections, content.scenes)
    present = {(kind, key) for kind, key, _ in await current_assets(session, row.id)}
    items = []
    for kind, key, version in versions:
        preview = next(iter(version.variants.values()), None)
        items.append(
            {
                "kind": kind,
                "label": LABELS[cast(Kind, kind)],
                "key": key,
                "filename": version.filename,
                "width": version.width,
                "height": version.height,
                "bytes": version.bytes,
                "warnings": version.warnings,
                "url": f"/assets/{preview}" if preview else None,
                "uploaded_at": version.created_at,
                # Обложка и иконки достижений пока ни с чем не связаны в данных — не «лишние».
                "used": (kind, key) in needed or kind in ("cover", "achievement", "avatar"),
            }
        )
    return {
        "assets": items,
        "missing": [
            {"kind": kind, "label": LABELS[kind], "key": key, "file": file_name(kind, key)}
            for kind, key in sorted(needed - present)
        ],
    }


# ── Песочница, превью, симулятор ────────────────────────────────────────


def get_catalog(request: Request) -> Catalog:
    return request.app.state.catalog


async def member_user(member: MemberDep) -> User:
    return member.user


async def _build_of(
    session: AsyncSession, request: Request, slug: str, build_id: int
) -> tuple[TitleRow, Build]:
    row = await _title(session, slug)
    build = await session.get(Build, build_id)
    if build is None or build.title_id != row.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "build not found")
    return row, build


async def sandbox_game(
    slug: str, build_id: int, request: Request, session: SessionDep, member: MemberDep
) -> play.Game:
    """Любая сборка тайтла — в песочнице сотрудника (слот sandbox:<сборка>)."""
    del member
    row, build = await _build_of(session, request, slug, build_id)
    loaded = await get_catalog(request).build(session, build.id)
    assert loaded is not None
    return play.Game(loaded, row.id, play.sandbox_slot(build.id))


game_routes(
    router, "/titles/{slug}/builds/{build_id}/sandbox", sandbox_game, member_user, debug=True
)


@router.post("/titles/{slug}/builds/{build_id}/preview")
async def preview(
    slug: str,
    build_id: int,
    request: Request,
    session: SessionDep,
    member: MemberDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Песочница на телефоне: бот присылает сотруднику кнопку, открывающую сборку в Mini App."""
    row, build = await _build_of(session, request, slug, build_id)
    if not settings.public_url:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "no_public_url"})
    token = await create_preview_token(session, build.id, member.user.id, datetime.now(UTC))
    await session.commit()
    url = f"{settings.public_url.rstrip('/')}/?preview={token}"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть превью", web_app=WebAppInfo(url=url))]]
    )
    try:
        await request.app.state.bot.send_message(
            member.user.tg_id,
            f"Превью «{row.name}», версия {build.version}. Ссылка действует 7 дней, "
            "прогресс — в песочнице, не в игре.",
            reply_markup=keyboard,
        )
        sent = True
    except Exception:
        # Бот может не достучаться (не нажат /start) — ссылка всё равно в ответе.
        sent = False
    return {"url": url, "sent": sent}


class SimulateRequest(BaseModel):
    players: int = Field(default=50, ge=1, le=MAX_PLAYERS)
    #: random, romance:<персонаж> или goal:<метрика>:max|min
    strategy: str = "random"
    scene_strategy: Literal["free", "random", "first"] = "free"
    session_gap_hours: float = Field(default=4, gt=0, le=72)
    horizon_hours: float = Field(default=24 * 14, gt=0, le=24 * 60)
    seed: int = 1


@router.post("/titles/{slug}/builds/{build_id}/simulate")
async def simulate_build(
    slug: str,
    build_id: int,
    body: SimulateRequest,
    request: Request,
    session: SessionDep,
    member: EditorDep,
) -> dict[str, Any]:
    """Симулятор баланса по сборке: отчёт в Markdown (docs/TITLE_FORMAT.md, «Симулятор»)."""
    del member
    _, build = await _build_of(session, request, slug, build_id)
    loaded = await get_catalog(request).build(session, build.id)
    assert loaded is not None
    if body.strategy.startswith("romance:"):
        focus = body.strategy.removeprefix("romance:")
        if focus not in loaded.title.characters:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"нет персонажа {focus}")
    elif body.strategy.startswith("goal:"):
        try:
            parse_goal(body.strategy, loaded.title)
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    elif body.strategy != "random":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "стратегия: random, romance:<персонаж> или goal:<метрика>:max|min",
        )
    settings = SimulationSettings(
        players=body.players,
        strategy=body.strategy,
        scene_strategy=body.scene_strategy,
        session_gap_hours=body.session_gap_hours,
        horizon_hours=body.horizon_hours,
        seed=body.seed,
    )
    try:
        return await asyncio.to_thread(simulate, loaded, settings)
    except EngineUnavailableError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from None


# ── Данные тайтла в формах ──────────────────────────────────────────────


@router.get("/schema")
async def schema(member: MemberDep) -> dict[str, Any]:
    """JSON Schema сущностей тайтла: студия строит по ним формы."""
    del member
    return documents.schemas()


@router.get("/titles/{slug}/documents")
async def title_documents(slug: str, session: SessionDep, member: MemberDep) -> dict[str, Any]:
    """Все данные тайтла по сущностям, ключи сцен и проблемы (без компиляции сцен)."""
    del member
    row = await _title(session, slug)
    return {
        **await documents.read_documents(session, row),
        "problems": await documents.problems(session, row),
    }


class DocumentRequest(BaseModel):
    data: Any


def _kind(kind: str) -> str:
    if kind not in documents.MODELS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown section")
    return kind


@router.put("/titles/{slug}/documents/{kind}/{key}")
async def put_document(
    slug: str, kind: str, key: str, body: DocumentRequest, session: SessionDep, member: EditorDep
) -> dict[str, Any]:
    """Сохранить сущность. Ошибки её полей — 422; ошибки ссылок по тайтлу — в ответе."""
    row = await _title(session, slug)
    errors = documents.validate_entity(_kind(kind), key, body.data)
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"errors": errors})
    await documents.save_document(session, row, kind, key, body.data, member.user.id)
    await session.commit()
    return {"problems": await documents.problems(session, row)}


@router.delete("/titles/{slug}/documents/{kind}/{key}")
async def remove_document(
    slug: str, kind: str, key: str, session: SessionDep, member: EditorDep
) -> dict[str, Any]:
    """Удалить сущность. Ключи опубликованной сборки сохранит проверка при публикации."""
    del member
    row = await _title(session, slug)
    if not await documents.delete_document(session, row, _kind(kind), key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    await session.commit()
    return {"problems": await documents.problems(session, row)}
