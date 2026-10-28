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
from PIL import Image
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
    assert {"slug": key, "name": "Мини", "days": None, "cover": None, "save": None} in catalog
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


def upload(client: TestClient, key: str, filename: str, data: bytes) -> Any:
    return client.post(
        f"/api/studio/titles/{key}/assets",
        files={"file": (filename, data, "application/octet-stream")},
        headers=HEADERS,
    )


def test_assets_reach_players_through_the_build(client: TestClient) -> None:
    from tests.test_assets import png

    studio(client)
    key = slug()
    files = {
        "title.yaml": CONFIG,
        "locations.yaml": LOCATIONS + "park: {name: Парк, background: park}\n",
    }
    post(client, f"/api/studio/titles/{key}/import", {"files": files})

    uploaded = upload(client, key, "bg_home.png", png((1440, 2560)))
    again = upload(client, key, "bg_home.png", png((1440, 2560)))
    listing = client.get(f"/api/studio/titles/{key}/assets").json()
    built = post(client, f"/api/studio/titles/{key}/builds", {}).json()
    post(client, f"/api/studio/titles/{key}/publish", {"build_id": built["id"]})
    player = {"Authorization": f"tma {make_init_data({'id': 43, 'first_name': 'И'})}"}
    game = client.get(f"/api/titles/{key}/game", headers=player).json()

    assert uploaded.json() == {
        "kind": "background",
        "key": "home",
        "unchanged": False,
        "warnings": [],
    }
    assert again.json()["unchanged"] is True
    assert [(a["kind"], a["key"], a["used"]) for a in listing["assets"]] == [
        ("background", "home", True)
    ]
    assert listing["missing"] == [
        {"kind": "background", "label": "фон", "key": "park", "file": "bg_park.png"}
    ]
    assert "нет ассета: фон park (bg_park.png) — будет заглушка" in built["warnings"]
    url = game["assets"]["background"]["home"]["1080"]
    assert url.startswith(f"/assets/t/{key}/")
    served = client.get(url)
    assert served.status_code == 200
    assert Image.open(BytesIO(served.content)).size == (1080, 1920)


def test_sprite_canvas_must_match_other_emotions(client: TestClient) -> None:
    from tests.test_assets import png

    studio(client)
    key = slug()
    post(client, f"/api/studio/titles/{key}/import", {"files": {"title.yaml": CONFIG}})

    first = upload(client, key, "anna_neutral.png", png((1000, 2400), "RGBA"))
    other = upload(client, key, "anna_happy.png", png((900, 2400), "RGBA"))

    assert first.status_code == 200
    assert other.status_code == 422
    assert "на одном холсте" in other.json()["detail"]["errors"][0]


def test_bad_asset_name_is_explained(client: TestClient) -> None:
    studio(client)
    key = slug()
    post(client, f"/api/studio/titles/{key}/import", {"files": {"title.yaml": CONFIG}})

    response = upload(client, key, "Gym.png", b"x")

    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0].startswith("Gym.png: имя — латиница")


def staff_tg_id(client: TestClient) -> int:
    """Telegram id сотрудника, вошедшего в студию этим клиентом."""
    member = client.get("/api/studio/me").json()

    async def work(session: AsyncSession) -> int:
        user = await session.get(User, member["id"])
        assert user is not None
        return user.tg_id

    return run_db(work)


def published_mini(client: TestClient) -> tuple[str, int]:
    key = slug()
    files = {
        "title.yaml": CONFIG,
        "locations.yaml": LOCATIONS + "park: {name: Парк, background: park}\n",
    }
    post(client, f"/api/studio/titles/{key}/import", {"files": files})
    build = post(client, f"/api/studio/titles/{key}/builds", {}).json()
    post(client, f"/api/studio/titles/{key}/publish", {"build_id": build["id"]})
    return key, build["id"]


def act_in(client: TestClient, base: str, action: dict[str, Any], **extra: Any) -> Any:
    body = {"request_id": str(uuid.uuid4()), "action": action}
    return client.post(f"{base}/actions", json=body, headers={**HEADERS, **extra})


def test_sandbox_is_separate_from_the_real_game(client: TestClient) -> None:
    studio(client)
    key, build_id = published_mini(client)
    sandbox = f"/api/studio/titles/{key}/builds/{build_id}/sandbox"
    player = {
        "Authorization": f"tma {make_init_data({'id': staff_tg_id(client), 'first_name': 'С'})}"
    }

    first = client.get(f"{sandbox}/state").json()
    moved = act_in(client, sandbox, {"type": "go", "location": "park"})
    real = client.get(f"/api/titles/{key}/state", headers=player).json()

    assert first["here"]["location"] == "home"
    assert moved.json()["here"]["location"] == "park"
    assert real["here"]["location"] == "home"
    assert client.get(f"{sandbox}/game").json()["name"] == "Мини"
    log = client.get(f"{sandbox}/debug/log").json()
    assert [entry["action"] for entry in log] == [{"type": "go", "location": "park"}]


def test_sandbox_debug_edits_state(client: TestClient) -> None:
    studio(client)
    key, build_id = published_mini(client)
    sandbox = f"/api/studio/titles/{key}/builds/{build_id}/sandbox"
    state = client.get(f"{sandbox}/state").json()["state"]

    edited = client.put(
        f"{sandbox}/debug/state",
        json={"state": {**state, "day": 5, "location": "park", "global_level": 3}},
        headers=HEADERS,
    )
    broken = client.put(
        f"{sandbox}/debug/state",
        json={"state": {**state, "location": "moon", "items": {"sword": 1}}},
        headers=HEADERS,
    )

    assert edited.status_code == 200
    assert edited.json()["time"]["day"] == 5
    assert edited.json()["here"]["location"] == "park"
    assert edited.json()["account"]["level"] == 3
    assert broken.status_code == 422
    assert broken.json()["detail"]["errors"] == ["нет локации moon", "нет предмета sword"]


def test_sandbox_does_not_grant_account_xp(client: TestClient) -> None:
    studio(client)
    key = slug()
    workout = (
        "gym: {name: Зал, location: home, cost: {slots: 0}, effects: {add: {global.xp: 40}}}\n"
    )
    files = {"title.yaml": CONFIG, "locations.yaml": LOCATIONS, "activities.yaml": workout}
    post(client, f"/api/studio/titles/{key}/import", {"files": files})
    build = post(client, f"/api/studio/titles/{key}/builds", {}).json()
    sandbox = f"/api/studio/titles/{key}/builds/{build['id']}/sandbox"
    player = {
        "Authorization": f"tma {make_init_data({'id': staff_tg_id(client), 'first_name': 'С'})}"
    }
    before = client.get("/api/profile", headers=player).json()["xp"]

    result = act_in(client, sandbox, {"type": "activity", "id": "gym"}).json()

    assert result["outcome"]["xp"] == 40
    assert client.get("/api/profile", headers=player).json()["xp"] == before


def test_preview_opens_sandbox_on_phone_for_staff_only(client: TestClient) -> None:
    from storymaker_api.studio.sandbox import create_preview_token

    studio(client)
    key, build_id = published_mini(client)
    staff_id = client.get("/api/studio/me").json()["id"]
    sandbox = f"/api/studio/titles/{key}/builds/{build_id}/sandbox"
    act_in(client, sandbox, {"type": "go", "location": "park"})

    async def issue(session: AsyncSession) -> str:
        token = await create_preview_token(session, build_id, staff_id, datetime.now(UTC))
        await session.commit()
        return token

    token = run_db(issue)
    staff = {
        "Authorization": f"tma {make_init_data({'id': staff_tg_id(client), 'first_name': 'С'})}"
    }
    stranger = {"Authorization": f"tma {make_init_data({'id': 7, 'first_name': 'Ч'})}"}

    phone = client.get(f"/api/preview/{token}/state", headers=staff)

    assert phone.status_code == 200
    # То же сохранение, что в песочнице студии.
    assert phone.json()["here"]["location"] == "park"
    assert client.get(f"/api/preview/{token}/state", headers=stranger).status_code == 404
    assert client.get("/api/preview/nope/state", headers=staff).status_code == 404


def test_preview_needs_public_url(client: TestClient) -> None:
    studio(client)
    key, build_id = published_mini(client)

    response = post(client, f"/api/studio/titles/{key}/builds/{build_id}/preview", {})

    assert response.status_code == 409


@needs_node
def test_simulator_runs_on_a_build(client: TestClient) -> None:
    studio(client)
    key = slug()
    post(client, f"/api/studio/titles/{key}/import", {"files": read_directory(DEMO)})
    build = post(client, f"/api/studio/titles/{key}/builds", {}).json()
    url = f"/api/studio/titles/{key}/builds/{build['id']}/simulate"

    report = post(client, url, {"players": 5, "strategy": "romance:anna"})
    unknown = post(client, url, {"players": 5, "strategy": "romance:nobody"})
    goal = post(client, url, {"players": 5, "strategy": "goal:stat.fitness:max"})
    bad_goal = post(client, url, {"players": 5, "strategy": "goal:stat.luck:max"})

    assert report.status_code == 200, report.json()
    assert report.json()["report"].startswith("# Симуляция «Неделя в новом городе»")
    assert unknown.status_code == 422
    assert "## Цель: Форма — максимизация" in goal.json()["report"]
    assert bad_goal.status_code == 422
    assert bad_goal.json()["detail"] == "нет метрики stat.luck"


def test_schema_marks_references_for_forms(client: TestClient) -> None:
    studio(client)

    schemas = client.get("/api/studio/schema").json()

    activity = schemas["activities"]["properties"]
    assert activity["location"]["x-ref"] == "locations"
    assert activity["location"]["title"] == "Локация"
    assert activity["requires"]["x-yaml"] is True
    assert set(schemas) == {
        "config",
        "characters",
        "map",
        "locations",
        "activities",
        "items",
        "quests",
        "events",
        "achievements",
    }


def test_documents_edit_one_entity_at_a_time(client: TestClient) -> None:
    studio(client)
    key = slug()
    events = "hello: {trigger: day_start, effects: {set: {flag.hi: true}}}\n"
    files = {"title.yaml": CONFIG, "locations.yaml": LOCATIONS, "events.yaml": events}
    post(client, f"/api/studio/titles/{key}/import", {"files": files})
    base = f"/api/studio/titles/{key}/documents"

    read = client.get(base).json()
    bad = client.put(
        f"{base}/activities/nap",
        json={"data": {"name": "Сон", "location": "home", "cost": {"slots": "много"}}},
        headers=HEADERS,
    )
    dangling = client.put(
        f"{base}/activities/nap",
        json={"data": {"name": "Сон", "location": "attic"}},
        headers=HEADERS,
    )
    fixed = client.put(
        f"{base}/activities/nap",
        json={"data": {"name": "Сон", "location": "home"}},
        headers=HEADERS,
    )
    wrong_key = client.put(f"{base}/config/other", json={"data": {"name": "x"}}, headers=HEADERS)

    assert read["sections"]["events"]["hello"]["trigger"] == {"on": "day_start"}
    assert read["sections"]["locations"]["home"]["name"] == "Дом"
    assert read["problems"]["errors"] == []
    assert bad.status_code == 422
    assert bad.json()["detail"]["errors"] == ["cost → slots: ожидается целое число"]
    assert any("attic" in e for e in dangling.json()["problems"]["errors"])
    assert fixed.json()["problems"]["errors"] == []
    assert wrong_key.status_code == 422
    assert client.get(base).json()["sections"]["activities"]["nap"]["location"] == "home"

    removed = client.delete(f"{base}/activities/nap", headers=HEADERS)
    assert removed.status_code == 200
    assert "nap" not in client.get(base).json()["sections"]["activities"]
    assert client.delete(f"{base}/activities/nap", headers=HEADERS).status_code == 404


def test_writer_cannot_edit_documents(client: TestClient) -> None:
    studio(client)
    key = slug()
    post(client, f"/api/studio/titles/{key}/import", {"files": {"title.yaml": CONFIG}})
    studio(client, "writer")

    response = client.put(
        f"/api/studio/titles/{key}/documents/locations/home",
        json={"data": {"name": "Дом", "background": "home"}},
        headers=HEADERS,
    )

    assert response.status_code == 403


SCENE_FILES = {
    "title.yaml": CONFIG.replace("{location: home}", "{location: home, flags: [tutorial]}")
    + "stats: {charm: {name: Обаяние}}\n",
    "locations.yaml": LOCATIONS,
    "characters.yaml": "anna: {name: Анна, color: '#f19bb8', emotions: [neutral, happy]}\n",
    "items.yaml": "rose: {name: Роза, kind: gift}\n",
    "events.yaml": "hi: {trigger: day_start, scene: hello, when: {flag.met_anna: true}}\n",
    "scenes/hello.ink": "# bg: home\n# music: calm\nanna: Привет.\n# effect: flag waved\n"
    '{ flag("seen_ending"): Снова ты. }\n-> END\n',
}


def test_scene_editor_gets_the_build_registry_and_hints(client: TestClient) -> None:
    key = slug()
    studio(client)
    post(client, f"/api/studio/titles/{key}/import", {"files": SCENE_FILES})
    studio(client, "writer")

    context = client.get(f"/api/studio/titles/{key}/scenes").json()

    assert [scene["key"] for scene in context["scenes"]] == ["hello"]
    assert context["registry"] == {
        "characters": {"anna": ["neutral", "happy"]},
        "items": ["rose"],
        "stats": ["charm"],
        "quests": [],
        "achievements": [],
    }
    assert context["characters"]["anna"] == {
        "name": "Анна",
        "color": "#f19bb8",
        "emotions": ["neutral", "happy"],
    }
    assert context["items"] == {"rose": "Роза"}
    assert context["flags"] == ["met_anna", "seen_ending", "tutorial", "waved"]
    assert context["backgrounds"] == ["home"]
    assert context["music"] == ["calm"]
    assert context["locations"]["home"] == {"name": "Дом", "background": "home"}


def test_scenes_are_saved_without_losing_someone_elses_edit(client: TestClient) -> None:
    studio(client)
    key = slug()
    post(client, f"/api/studio/titles/{key}/import", {"files": {"title.yaml": CONFIG}})
    studio(client, "writer")
    url = f"/api/studio/titles/{key}/scenes/intro"

    created = client.put(url, json={"source": "Привет.\n-> END\n"}, headers=HEADERS)
    twice = client.put(url, json={"source": "Другое.\n"}, headers=HEADERS)
    opened = client.get(url).json()
    saved = client.put(
        url, json={"source": "Привет!\n-> END\n", "base": opened["updated_at"]}, headers=HEADERS
    )
    stale = client.put(
        url, json={"source": "Затираю.\n", "base": opened["updated_at"]}, headers=HEADERS
    )

    assert created.status_code == 200, created.json()
    assert any("intro" in w for w in created.json()["problems"]["warnings"])
    assert twice.status_code == 409
    assert twice.json()["detail"]["exists"] is True
    assert saved.status_code == 200, saved.json()
    assert stale.status_code == 409
    assert stale.json()["detail"]["updated_by"] == "Сотрудник"
    assert client.get(url).json()["source"] == "Привет!\n-> END\n"

    bad = client.put(
        f"/api/studio/titles/{key}/scenes/Intro", json={"source": "x"}, headers=HEADERS
    )
    assert bad.status_code == 422
    assert client.delete(url, headers=HEADERS).status_code == 200
    assert client.get(url).status_code == 404
    assert client.delete(url, headers=HEADERS).status_code == 404
