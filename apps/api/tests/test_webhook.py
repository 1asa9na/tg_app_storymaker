from fastapi.testclient import TestClient

from tests.conftest import WEBHOOK_SECRET

# Апдейт, на который у бота нет обработчика: он не пойдёт в Telegram API.
UPDATE = {
    "update_id": 1,
    "message": {
        "message_id": 1,
        "date": 1760000000,
        "chat": {"id": 42, "type": "private"},
        "from": {"id": 42, "is_bot": False, "first_name": "Анна"},
        "text": "привет",
    },
}


def test_webhook_rejects_missing_secret(client: TestClient) -> None:
    assert client.post("/bot/webhook", json=UPDATE).status_code == 401


def test_webhook_rejects_wrong_secret(client: TestClient) -> None:
    headers = {"X-Telegram-Bot-Api-Secret-Token": "wrong"}

    assert client.post("/bot/webhook", json=UPDATE, headers=headers).status_code == 401


def test_webhook_accepts_update_with_secret(client: TestClient) -> None:
    headers = {"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET}

    assert client.post("/bot/webhook", json=UPDATE, headers=headers).status_code == 200
