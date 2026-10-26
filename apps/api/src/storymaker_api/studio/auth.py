"""Вход в студию: бот присылает одноразовую ссылку → студия меняет её на cookie-сессию.

Токены и сессии хранятся только хешами. Роли:
- admin — всё, включая команду;
- designer — данные тайтлов, сборка, публикация;
- writer — сцены (редактор — этап 4), остальное только смотрит.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, cast

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api.db import get_session
from storymaker_api.models import LoginToken, Staff, StudioSession, User

Role = Literal["admin", "designer", "writer"]
ROLES: tuple[Role, ...] = ("admin", "designer", "writer")

COOKIE = "studio_session"
LOGIN_TTL = timedelta(minutes=10)
SESSION_TTL = timedelta(days=30)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def staff_role(session: AsyncSession, user_id: int) -> Role | None:
    role = await session.scalar(select(Staff.role).where(Staff.user_id == user_id))
    return cast(Role, role) if role in ROLES else None


async def create_login_token(session: AsyncSession, user_id: int, now: datetime) -> str:
    token = secrets.token_urlsafe(32)
    session.add(LoginToken(token_hash=_hash(token), user_id=user_id, expires_at=now + LOGIN_TTL))
    await session.flush()
    return token


async def exchange_login_token(
    session: AsyncSession, token: str, now: datetime
) -> tuple[str, User] | None:
    """Одноразовый токен → новая сессия. None — токен неверный, использован или истёк."""
    login = await session.scalar(
        select(LoginToken).where(LoginToken.token_hash == _hash(token)).with_for_update()
    )
    if login is None or login.used_at is not None or login.expires_at <= now:
        return None
    login.used_at = now
    if await staff_role(session, login.user_id) is None:
        return None
    user = await session.get(User, login.user_id)
    assert user is not None
    session_token = secrets.token_urlsafe(32)
    session.add(
        StudioSession(
            token_hash=_hash(session_token), user_id=user.id, expires_at=now + SESSION_TTL
        )
    )
    await session.flush()
    return session_token, user


async def end_session(session: AsyncSession, token: str) -> None:
    found = await session.get(StudioSession, _hash(token))
    if found is not None:
        await session.delete(found)


class Member:
    """Сотрудник запроса."""

    def __init__(self, user: User, role: Role) -> None:
        self.user = user
        self.role = role


async def current_member(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    token: Annotated[str | None, Cookie(alias=COOKIE)] = None,
    x_studio: Annotated[str | None, Header()] = None,
) -> Member:
    """Сотрудник по cookie-сессии. Изменяющие запросы — только с заголовком X-Studio:
    сторонний сайт не может прислать его без CORS-разрешения, это защита от CSRF."""
    if request.method not in ("GET", "HEAD") and x_studio != "1":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing X-Studio header")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not logged in")
    found = await session.get(StudioSession, _hash(token))
    if found is None or found.expires_at <= datetime.now(UTC):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")
    role = await staff_role(session, found.user_id)
    user = await session.get(User, found.user_id)
    if role is None or user is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not in staff")
    return Member(user, role)


def require(*roles: Role):
    """Зависимость: сотрудник с одной из ролей (admin проходит всегда)."""

    async def dependency(member: Annotated[Member, Depends(current_member)]) -> Member:
        if member.role != "admin" and member.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not allowed for your role")
        return member

    return dependency
