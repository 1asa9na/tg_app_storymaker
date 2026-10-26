"""Опубликованные тайтлы для плеера: активные сборки из базы с кэшем в памяти.

Сборка не меняется после создания, поэтому кэш по id не устаревает: публикация новой
сборки меняет только titles.active_build_id.
"""

from collections import OrderedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api.game.registry import TitleBuild
from storymaker_api.models import Build, TitleRow

CACHE_SIZE = 32


class Catalog:
    def __init__(self) -> None:
        self._builds: OrderedDict[int, TitleBuild] = OrderedDict()

    async def build(self, session: AsyncSession, build_id: int) -> TitleBuild | None:
        if build_id in self._builds:
            self._builds.move_to_end(build_id)
            return self._builds[build_id]
        data = await session.scalar(select(Build.data).where(Build.id == build_id))
        if data is None:
            return None
        build = TitleBuild.from_json(data)
        self._builds[build_id] = build
        while len(self._builds) > CACHE_SIZE:
            self._builds.popitem(last=False)
        return build

    async def published(self, session: AsyncSession) -> list[tuple[TitleRow, TitleBuild]]:
        rows = await session.scalars(
            select(TitleRow)
            .where(TitleRow.status == "published", TitleRow.active_build_id.is_not(None))
            .order_by(TitleRow.sort, TitleRow.id)
        )
        result = []
        for row in rows:
            assert row.active_build_id is not None
            build = await self.build(session, row.active_build_id)
            if build is not None:
                result.append((row, build))
        return result

    async def get(self, session: AsyncSession, slug: str) -> tuple[TitleRow, TitleBuild] | None:
        """Опубликованный тайтл; скрытый (hidden) тоже открывается — у игроков есть сохранения."""
        row = await session.scalar(select(TitleRow).where(TitleRow.slug == slug))
        if row is None or row.status == "draft" or row.active_build_id is None:
            return None
        build = await self.build(session, row.active_build_id)
        return (row, build) if build else None
