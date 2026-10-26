import random
import shutil
import uuid
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api.game.loader import read_directory
from storymaker_api.game.scenes import ENGINE_DIR
from storymaker_api.main import create_app
from storymaker_api.models import Staff, User
from storymaker_api.studio.auth import create_login_token
from tests.conftest import make_init_data, run_db

DEMO = Path(__file__).parents[3] / "content" / "titles" / "demo"
needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not (ENGINE_DIR / "node_modules").exists(),
    reason="сборка сцен требует Node и packages/engine",
)
HEADERS = {"X-Studio": "1"}

CONFIG = """
name: Мини
time:
  slots: [{id: day, name: День}]
start: {location: home}
"""
LOCATIONS = "home: {name: Дом, background: home}\n"


def login_token(role: str | None) -> str:
    """Пользователь (в команде с ролью или без) и одноразовый токен входа для него."""

    async def work(session: AsyncSession) -> str:
        user = User(tg_id=random.randint(10**9, 10**10), first_name="Сотрудник")
        session.add(user)
        await session.flush()
        if role:
            session.add(Staff(user_id=user.id, role=role))
        token = await create_login_token(session, user.id, datetime.now(UTC))
        await session.commit()
        return token

    return run_db(work)


@pytest.fixture
def client(migrated_database: None) -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def studio(client: TestClient, role: str = "designer") -> TestClient:
    response = client.post("/api/studio/login", json={"token": login_token(role)})
    assert response.status_code == 200, response.json()
    return client


def slug() -> str:
    return f"t{uuid.uuid4().hex[:10]}"


def post(client: TestClient, path: str, body: dict[str, Any]) -> Any:
    return client.post(path, json=body, headers=HEADERS)


def test_login_link_works_once(client: TestClient) -> None:
    token = login_token("designer")

    first = client.post("/api/studio/login", json={"token": token})
    me = client.get("/api/studio/me")
    again = client.post("/api/studio/login", json={"token": token})

    assert first.status_code == 200
    assert first.json()["role"] == "designer"
    assert me.json()["role"] == "designer"
    assert again.status_code == 401


def test_only_staff_can_log_in(client: TestClient) -> None:
    assert client.post("/api/studio/login", json={"token": login_token(None)}).status_code == 401
    assert client.post("/api/studio/login", json={"token": "x" * 40}).status_code == 401
    assert client.get("/api/studio/me").status_code == 401


def test_logout_ends_session(client: TestClient) -> None:
    studio(client)

    assert post(client, "/api/studio/logout", {}).status_code == 200
    assert client.get("/api/studio/me").status_code == 401


def test_changes_require_studio_header(client: TestClient) -> None:
    studio(client)

    response = client.post(f"/api/studio/titles/{slug()}/import", json={"files": {}})

    assert response.status_code == 403


def test_writer_cannot_import(client: TestClient) -> None:
    studio(client, "writer")

    response = post(client, f"/api/studio/titles/{slug()}/import", {"files": {}})

    assert response.status_code == 403


def test_import_reports_yaml_errors(client: TestClient) -> None:
    studio(client)

    response = post(
        client,
        f"/api/studio/titles/{slug()}/import",
        {"files": {"title.yaml": "name: [", "notes.txt": "x"}},
    )

    assert response.status_code == 422
    errors = response.json()["detail"]["errors"]
    assert any(e.startswith("title.yaml: ошибка YAML") for e in errors)
    assert "notes.txt: неизвестный файл" in errors


def test_build_with_errors_is_not_saved(client: TestClient) -> None:
    studio(client)
    key = slug()
    broken = CONFIG.replace("{location: home}", "{location: nowhere}")
    post(client, f"/api/studio/titles/{key}/import", {"files": {"title.yaml": broken}})

    response = post(client, f"/api/studio/titles/{key}/builds", {})

    assert response.status_code == 422
    assert response.json()["detail"]["errors"]
    assert client.get(f"/api/studio/titles/{key}").json()["builds"] == []


def test_publish_flow_reaches_players(client: TestClient) -> None:
    studio(client)
    key = slug()
    files = {"title.yaml": CONFIG, "locations.yaml": LOCATIONS}

    imported = post(client, f"/api/studio/titles/{key}/import", {"files": files})
    built = post(client, f"/api/studio/titles/{key}/builds", {"notes": "первая"})
    player = {"Authorization": f"tma {make_init_data({'id': 42, 'first_name': 'И'})}"}
    hidden_before = key not in [t["slug"] for t in client.get("/api/titles", headers=player).json()]
    published = post(client, f"/api/studio/titles/{key}/publish", {"build_id": built.json()["id"]})

    assert imported.json() == {"slug": key, "name": "Мини"}
    assert built.status_code == 200
    assert built.json()["version"] == 1
    assert hidden_before
    assert published.json() == {"slug": key, "active_version": 1, "status": "published"}
    catalog = client.get("/api/titles", headers=player).json()
    assert {"slug": key, "name": "Мини", "days": None, "save": None} in catalog
    state = client.get(f"/api/titles/{key}/state", headers=player).json()
    assert state["here"]["location"] == "home"

    post(client, f"/api/studio/titles/{key}/status", {"status": "hidden"})
    assert key not in [t["slug"] for t in client.get("/api/titles", headers=player).json()]
    assert client.get(f"/api/titles/{key}/state", headers=player).status_code == 200


def test_publish_refuses_to_lose_ids(client: TestClient) -> None:
    studio(client)
    key = slug()
    two = LOCATIONS + "park: {name: Парк, background: park}\n"
    post(
        client,
        f"/api/studio/titles/{key}/import",
        {"files": {"title.yaml": CONFIG, "locations.yaml": two}},
    )
    first = post(client, f"/api/studio/titles/{key}/builds", {}).json()
    post(client, f"/api/studio/titles/{key}/publish", {"build_id": first["id"]})
    post(
        client,
        f"/api/studio/titles/{key}/import",
        {"files": {"title.yaml": CONFIG, "locations.yaml": LOCATIONS}},
    )
    second = post(client, f"/api/studio/titles/{key}/builds", {}).json()

    refused = post(client, f"/api/studio/titles/{key}/publish", {"build_id": second["id"]})
    forced_by_designer = post(
        client, f"/api/studio/titles/{key}/publish", {"build_id": second["id"], "force": True}
    )

    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "lost_ids", "lost": ["локация park"]}
    assert forced_by_designer.status_code == 403
    studio(client, "admin")
    forced = post(
        client, f"/api/studio/titles/{key}/publish", {"build_id": second["id"], "force": True}
    )
    assert forced.json()["active_version"] == 2
    # Откат — публикация старой сборки: park снова есть, ничего не теряется.
    rollback = post(client, f"/api/studio/titles/{key}/publish", {"build_id": first["id"]})
    assert rollback.json()["active_version"] == 1


def test_export_round_trips(client: TestClient) -> None:
    studio(client)
    key = slug()
    files = {"title.yaml": CONFIG, "locations.yaml": LOCATIONS}
    post(client, f"/api/studio/titles/{key}/import", {"files": files})

    response = client.get(f"/api/studio/titles/{key}/export")

    archive = zipfile.ZipFile(BytesIO(response.content))
    assert sorted(archive.namelist()) == [f"{key}/locations.yaml", f"{key}/title.yaml"]
    exported = {
        name.removeprefix(f"{key}/"): archive.read(name).decode() for name in archive.namelist()
    }
    again = post(client, f"/api/studio/titles/{slug()}/import", {"files": exported})
    assert again.status_code == 200


@needs_node
def test_demo_title_builds_from_repository_files(client: TestClient) -> None:
    studio(client)
    key = slug()
    post(client, f"/api/studio/titles/{key}/import", {"files": read_directory(DEMO)})

    built = post(client, f"/api/studio/titles/{key}/builds", {})

    assert built.status_code == 200, built.json()
    detail = client.get(f"/api/studio/titles/{key}").json()
    assert detail["scenes"] == 4
    assert detail["documents"]["locations"] == 4


@needs_node
def test_seed_imports_repository_titles_once(client: TestClient) -> None:
    from storymaker_api.studio.__main__ import seed

    key = slug()
    content = {key: read_directory(DEMO)}

    first = run_db(lambda session: seed(session, content))
    second = run_db(lambda session: seed(session, content))

    assert (first, second) == (0, 0)
    studio(client)
    detail = client.get(f"/api/studio/titles/{key}").json()
    assert detail["status"] == "published"
    assert [b["version"] for b in detail["builds"]] == [1]
