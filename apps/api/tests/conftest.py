import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import time
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from urllib.parse import urlencode

# Настройки задаём до импорта приложения. Пустые значения перекрывают локальный .env:
# тесты не должны регистрировать вебхук и слать ошибки в Sentry.
os.environ["BOT_TOKEN"] = "123456:TEST-TOKEN"
os.environ["BOT_WEBHOOK_SECRET"] = "test-secret"
os.environ["PUBLIC_URL"] = ""
os.environ["SENTRY_DSN"] = ""
# Варианты ассетов — во временную папку (на сервере это /srv/assets).
os.environ["ASSETS_DIR"] = tempfile.mkdtemp(prefix="storymaker-assets-")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://storymaker:storymaker@localhost:5432/storymaker_test"
)

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from storymaker_api.db import create_engine
from storymaker_api.game.registry import TitleBuild, dump_title
from storymaker_api.game.schema import Title
from storymaker_api.main import create_app
from storymaker_api.models import Build, TitleRow
from tests.game.conftest import TITLE

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ["BOT_WEBHOOK_SECRET"]


def run_db[T](work: "Callable[[AsyncSession], Awaitable[T]]") -> T:
    """Запрос к тестовой базе из синхронного теста — в своём event loop и своём движке."""

    async def main() -> T:
        engine = create_engine(os.environ["DATABASE_URL"])
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await work(session)
        finally:
            await engine.dispose()

    return asyncio.run(main())


async def _publish_test_title(session: AsyncSession) -> None:
    """Тестовый тайтл движка (slug test) — опубликованной сборкой, как после студии."""
    title = await session.scalar(select(TitleRow).where(TitleRow.slug == "test"))
    if title is not None and title.active_build_id is not None:
        return
    if title is None:
        title = TitleRow(slug="test", name="Тест", sort=-1)
        session.add(title)
        await session.flush()
    data = dump_title(Title.model_validate(TITLE))
    build = Build(title_id=title.id, version=1, hash=TitleBuild.from_json(data).build, data=data)
    session.add(build)
    await session.flush()
    title.active_build_id = build.id
    title.status = "published"
    await session.commit()


@pytest.fixture(scope="session")
def migrated_database() -> None:
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    run_db(_publish_test_title)


@pytest.fixture
def client(migrated_database: None) -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def make_init_data(
    user: dict[str, object], *, token: str = BOT_TOKEN, auth_date: int | None = None
) -> str:
    """Подписанный initData — так же, как его подписывает Telegram."""
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        # Ed25519-подпись для сторонних сервисов; Telegram передаёт её с Bot API 8.0,
        # и она входит в строку, по которой считается hash.
        "signature": "dGVzdC1zaWduYXR1cmU",
        "user": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)
