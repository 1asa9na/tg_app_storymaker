"""Проверка окружения: база, Telegram Bot API, Supabase Storage.

На сервере: docker compose run --rm api python -m storymaker_api.doctor
"""

import asyncio
import base64
import sys
import uuid
from collections.abc import Awaitable, Callable

import boto3
import httpx
from botocore.config import Config
from sqlalchemy import text

from storymaker_api.bot import create_bot
from storymaker_api.config import Settings, get_settings
from storymaker_api.db import create_engine

# Валидный WebP 1×1: бакет assets принимает только разрешённые типы файлов.
TINY_WEBP = base64.b64decode("UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA==")
IMMUTABLE = "public, max-age=31536000, immutable"


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
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
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
