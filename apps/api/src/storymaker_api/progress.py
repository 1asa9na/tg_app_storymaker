"""Глобальный прогресс: опыт, уровень аккаунта и достижения — общие для всех тайтлов."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api.models import AccountProgress, UserAchievement

#: Опыт до уровня L: 25·L·(L−1) — 2-й за 50, 3-й за 150, 4-й за 300, 5-й за 500.
#: Кривая уедет в данные платформы вместе со студией.
XP_STEP = 25


def xp_for_level(level: int) -> int:
    return XP_STEP * level * (level - 1)


def level_for_xp(xp: int) -> int:
    level = 1
    while xp_for_level(level + 1) <= xp:
        level += 1
    return level


@dataclass
class Account:
    xp: int
    level: int
    level_up: bool = False

    @property
    def next_level_xp(self) -> int:
        return xp_for_level(self.level + 1)

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "xp": self.xp,
            "level": self.level,
            "level_xp": xp_for_level(self.level),
            "next_level_xp": self.next_level_xp,
            "level_up": self.level_up,
        }


async def get_account(session: AsyncSession, user_id: int) -> Account:
    row = await session.get(AccountProgress, user_id)
    return Account(xp=row.xp, level=row.level) if row else Account(xp=0, level=1)


async def add_progress(
    session: AsyncSession,
    user_id: int,
    title_id: int,
    xp: int,
    achievements: list[str],
) -> tuple[Account, list[str]]:
    """Начисляет опыт и достижения в текущей транзакции. Возвращает аккаунт и новые достижения."""
    before = await get_account(session, user_id)
    if xp > 0:
        total = await session.scalar(
            insert(AccountProgress)
            .values(user_id=user_id, xp=xp, level=level_for_xp(xp))
            .on_conflict_do_update(
                index_elements=[AccountProgress.user_id],
                set_={"xp": AccountProgress.xp + xp},
            )
            .returning(AccountProgress.xp)
        )
        assert total is not None
        level = level_for_xp(total)
        row = await session.get(AccountProgress, user_id, populate_existing=True)
        assert row is not None
        row.level = level
        account = Account(xp=total, level=level, level_up=level > before.level)
    else:
        account = before

    unlocked: list[str] = []
    if achievements:
        unlocked = list(
            await session.scalars(
                insert(UserAchievement)
                .values(
                    [
                        {"user_id": user_id, "title_id": title_id, "achievement_key": key}
                        for key in achievements
                    ]
                )
                .on_conflict_do_nothing()
                .returning(UserAchievement.achievement_key)
            )
        )
    return account, unlocked


async def list_achievements(session: AsyncSession, user_id: int) -> list[UserAchievement]:
    return list(
        await session.scalars(
            select(UserAchievement)
            .where(UserAchievement.user_id == user_id)
            .order_by(UserAchievement.unlocked_at, UserAchievement.id)
        )
    )
