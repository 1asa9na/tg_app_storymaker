import hashlib
import hmac
import json
import os
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlencode

# Настройки задаём до импорта приложения. Пустые значения перекрывают локальный .env:
# тесты не должны регистрировать вебхук и слать ошибки в Sentry.
os.environ["BOT_TOKEN"] = "123456:TEST-TOKEN"
os.environ["BOT_WEBHOOK_SECRET"] = "test-secret"
os.environ["PUBLIC_URL"] = ""
os.environ["SENTRY_DSN"] = ""
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://storymaker:storymaker@localhost:5432/storymaker_test"
)

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from storymaker_api.game.registry import dump_title
from storymaker_api.game.schema import Title
from storymaker_api.main import create_app
from tests.game.conftest import TITLE

# Тайтлы для API — тестовый тайтл движка, собранный в JSON, как при сборке образа.
TITLES_DIR = Path(tempfile.mkdtemp(prefix="storymaker-titles-"))
(TITLES_DIR / "test.json").write_text(dump_title(Title.model_validate(TITLE)), encoding="utf-8")
os.environ["TITLES_DIR"] = str(TITLES_DIR)

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ["BOT_WEBHOOK_SECRET"]


@pytest.fixture(scope="session")
def migrated_database() -> None:
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")


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
