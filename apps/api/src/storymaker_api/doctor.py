"""Проверка окружения: база, Telegram Bot API, Supabase Storage.

На сервере: docker compose run --rm api python -m storymaker_api.doctor
"""

import asyncio
import base64
import sys
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import ClientError
from sqlalchemy import text

from storymaker_api.bot import create_bot
from storymaker_api.config import Settings, get_settings
from storymaker_api.db import create_engine

# Валидный WebP 1×1: бакет assets принимает только разрешённые типы файлов.
TINY_WEBP = base64.b64decode("UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA==")
IMMUTABLE = "public, max-age=31536000, immutable"
# Supabase не принимает контрольные суммы, которые boto3 ≥ 1.36 добавляет к каждой загрузке.
S3_CONFIG = Config(
    signature_version="s3v4",
    s3={"addressing_style": "path"},
    request_checksum_calculation="when_required",
    response_checksum_validation="when_required",
)


class Skipped(Exception):
    pass


async def check_database(settings: Settings) -> str:
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            version = (await connection.execute(text("SHOW server_version"))).scalar_one()
    finally:
        await engine.dispose()
    return f"PostgreSQL {version}"


async def check_telegram(settings: Settings) -> str:
    bot = create_bot(settings)
    try:
        me = await bot.get_me()
        info = await bot.get_webhook_info()
    finally:
        await bot.session.close()
    webhook = info.url or "не задан"
    detail = f"@{me.username}, вебхук: {webhook}, в очереди: {info.pending_update_count}"
    if info.last_error_message:
        detail += f", последняя ошибка вебхука: {info.last_error_message}"
    return detail


def check_storage_sync(settings: Settings) -> str:
    secret = settings.s3_secret_access_key
    if not (settings.s3_endpoint_url and settings.s3_access_key_id and secret):
        raise Skipped("S3_* переменные не заданы")
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=secret.get_secret_value(),
        config=S3_CONFIG,
    )
    try:
        return _exercise_storage(s3, settings)
    except ClientError as error:
        raise RuntimeError(_describe(error, settings)) from error


def _describe(error: ClientError, settings: Settings) -> str:
    """Ошибка S3 с подробностями: Supabase иногда отвечает не XML, и botocore теряет причину."""
    response: Any = error.response
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    code = response.get("Error", {}).get("Code") or "без кода"
    message = response.get("Error", {}).get("Message") or ""
    operation = error.operation_name
    lines = [
        f"{operation}: HTTP {status}, {code} {message}".rstrip(),
        f"  endpoint: {settings.s3_endpoint_url}",
        f"  регион: {settings.s3_region}, бакеты: {settings.s3_bucket_assets}, "
        f"{settings.s3_bucket_originals}",
    ]
    body = response.get("_raw_body", b"")
    if body:
        lines.append(f"  ответ: {body[:300].decode(errors='replace')}")
    if status == 404 and "/storage/v1/s3" not in (settings.s3_endpoint_url or ""):
        lines.append("  подсказка: endpoint должен заканчиваться на /storage/v1/s3")
    return "\n".join(lines)


def _exercise_storage(s3: Any, settings: Settings) -> str:
    def keep_body(http_response: Any, parsed: Any, **_: Any) -> None:
        if http_response.status_code >= 300:
            parsed.setdefault("_raw_body", http_response.content)

    s3.meta.events.register("after-call.s3", keep_body)
    key = f"_doctor/{uuid.uuid4().hex}.webp"
    assets, originals = settings.s3_bucket_assets, settings.s3_bucket_originals

    s3.put_object(
        Bucket=assets, Key=key, Body=TINY_WEBP, ContentType="image/webp", CacheControl=IMMUTABLE
    )
    cache_control = s3.head_object(Bucket=assets, Key=key).get("CacheControl")
    s3.delete_object(Bucket=assets, Key=key)

    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": originals, "Key": key, "ContentType": "image/webp"},
        ExpiresIn=300,
    )
    response = httpx.put(
        upload_url, content=TINY_WEBP, headers={"Content-Type": "image/webp"}, timeout=30
    )
    response.raise_for_status()
    s3.head_object(Bucket=originals, Key=key)
    s3.delete_object(Bucket=originals, Key=key)

    if cache_control != IMMUTABLE:
        raise RuntimeError(f"Cache-Control не сохранился: {cache_control!r}")
    return f"запись в {assets}, presigned-загрузка в {originals}, Cache-Control сохраняется"


async def check_storage(settings: Settings) -> str:
    return await asyncio.to_thread(check_storage_sync, settings)


async def main() -> int:
    settings = get_settings()
    checks: list[tuple[str, Callable[[Settings], Awaitable[str]]]] = [
        ("База данных", check_database),
        ("Telegram Bot API", check_telegram),
        ("Supabase Storage", check_storage),
    ]
    failed = False
    for name, check in checks:
        try:
            print(f"✓ {name}: {await check(settings)}")
        except Skipped as skipped:
            print(f"– {name}: пропущено ({skipped})")
        except Exception as error:
            failed = True
            print(f"✗ {name}: {type(error).__name__}: {error}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
