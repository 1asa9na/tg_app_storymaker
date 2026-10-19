from fastapi.testclient import TestClient


def test_healthz_checks_database(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "env": "local"}
