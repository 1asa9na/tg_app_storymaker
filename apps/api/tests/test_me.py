import random
import time
from urllib.parse import parse_qsl, urlencode

from fastapi.testclient import TestClient

from tests.conftest import make_init_data


def random_user(**overrides: object) -> dict[str, object]:
    return {
        "id": random.randint(10**9, 10**10),
        "first_name": "Анна",
        "username": "anna",
        "language_code": "ru",
        **overrides,
    }


def auth(init_data: str) -> dict[str, str]:
    return {"Authorization": f"tma {init_data}"}


def test_me_creates_user_then_updates_profile(client: TestClient) -> None:
    user = random_user()

    first = client.get("/api/me", headers=auth(make_init_data(user)))
    second = client.get("/api/me", headers=auth(make_init_data({**user, "first_name": "Аня"})))

    assert first.status_code == 200
    assert first.json()["tg_id"] == user["id"]
    assert first.json()["first_name"] == "Анна"
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["first_name"] == "Аня"


def test_me_requires_init_data(client: TestClient) -> None:
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer x"}).status_code == 401


def test_me_rejects_tampered_init_data(client: TestClient) -> None:
    fields = dict(parse_qsl(make_init_data(random_user())))
    fields["user"] = fields["user"].replace("Анна", "Админ")

    response = client.get("/api/me", headers=auth(urlencode(fields)))

    assert response.status_code == 401


def test_me_rejects_init_data_signed_by_another_bot(client: TestClient) -> None:
    init_data = make_init_data(random_user(), token="654321:OTHER-TOKEN")

    assert client.get("/api/me", headers=auth(init_data)).status_code == 401


def test_me_rejects_expired_init_data(client: TestClient) -> None:
    two_days_ago = int(time.time()) - 2 * 24 * 60 * 60
    init_data = make_init_data(random_user(), auth_date=two_days_ago)

    response = client.get("/api/me", headers=auth(init_data))

    assert response.status_code == 401
    assert response.json()["detail"] == "init data expired"
