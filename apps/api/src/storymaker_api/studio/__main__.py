"""Команда и контент студии с сервера.

docker exec storymaker-staging-api-1 python -m storymaker_api.studio staff add 123456789 admin
docker exec storymaker-staging-api-1 python -m storymaker_api.studio staff list
docker exec storymaker-staging-api-1 python -m storymaker_api.studio staff remove 123456789
python -m storymaker_api.studio seed   # при деплое: тайтлы из репозитория, которых нет в базе
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from storymaker_api.config import get_settings
from storymaker_api.content import create_build, get_or_create_title, import_files, publish
from storymaker_api.db import create_engine
from storymaker_api.game.loader import Files, read_directory
from storymaker_api.models import Staff, TitleDocument, User
from storymaker_api.studio.auth import ROLES


async def staff_add(session: AsyncSession, tg_id: int, role: str) -> int:
    user = await session.scalar(select(User).where(User.tg_id == tg_id))
    if user is None:
        print(
            f"✗ пользователь {tg_id} ещё не заходил: пусть откроет бота и нажмёт /start",
            file=sys.stderr,
        )
        return 1
    await session.execute(
        insert(Staff)
        .values(user_id=user.id, role=role)
        .on_conflict_do_update(index_elements=[Staff.user_id], set_={"role": role})
    )
    await session.commit()
    print(f"✓ {user.first_name} (@{user.username or '—'}): {role}")
    return 0


async def staff_list(session: AsyncSession) -> int:
    rows = await session.execute(
        select(User.tg_id, User.first_name, User.username, Staff.role)
        .join(Staff, Staff.user_id == User.id)
        .order_by(Staff.created_at)
    )
    for tg_id, name, username, role in rows:
        print(f"{tg_id}\t{role}\t{name} (@{username or '—'})")
    return 0


async def staff_remove(session: AsyncSession, tg_id: int) -> int:
    user_id = await session.scalar(select(User.id).where(User.tg_id == tg_id))
    if user_id is not None:
        await session.execute(delete(Staff).where(Staff.user_id == user_id))
        await session.commit()
    print(f"✓ {tg_id} больше не в команде")
    return 0


def read_content(root: Path | None) -> dict[str, Files]:
    """Папки тайтлов из репозитория: slug → файлы."""
    if root is None or not root.is_dir():
        return {}
    return {
        path.parent.name: read_directory(path.parent) for path in sorted(root.glob("*/title.yaml"))
    }


async def seed(session: AsyncSession, content: dict[str, Files]) -> int:
    """Тайтлы из репозитория, которых ещё нет в базе: импорт, сборка, публикация.

    Тайтл, уже заведённый в базе, не трогается: дальше его ведут в студии.
    """
    if not content:
        print("– seed: CONTENT_DIR не задан или пуст, пропущено")
        return 0
    failed = False
    for slug, files in content.items():
        title = await get_or_create_title(session, slug, slug)
        has_content = await session.scalar(
            select(TitleDocument.id).where(TitleDocument.title_id == title.id).limit(1)
        )
        if has_content:
            print(f"– {title.slug}: уже в базе")
            await session.rollback()
            continue
        errors = await import_files(session, title, files, None)
        result = None if errors else await create_build(session, title, None, "из репозитория")
        if errors or result is None or result.build is None:
            for error in errors or (result.errors if result else []):
                print(f"✗ {title.slug}: {error}", file=sys.stderr)
            failed = True
            await session.rollback()
            continue
        await publish(session, title, result.build)
        await session.commit()
        print(f"✓ {title.slug}: импортирован и опубликован (версия {result.build.version})")
    return 1 if failed else 0


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    content = read_content(settings.content_dir) if args.command == "seed" else {}
    engine = create_engine(settings.database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            match args.command, getattr(args, "action", None):
                case "staff", "add":
                    return await staff_add(session, args.tg_id, args.role)
                case "staff", "list":
                    return await staff_list(session)
                case "staff", "remove":
                    return await staff_remove(session, args.tg_id)
                case "seed", _:
                    return await seed(session, content)
                case _:
                    return 2
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m storymaker_api.studio")
    commands = parser.add_subparsers(dest="command", required=True)
    staff = commands.add_parser("staff", help="команда студии").add_subparsers(
        dest="action", required=True
    )
    add = staff.add_parser("add", help="добавить или сменить роль")
    add.add_argument("tg_id", type=int, help="Telegram id (узнать: @userinfobot)")
    add.add_argument("role", choices=ROLES)
    staff.add_parser("list")
    remove = staff.add_parser("remove")
    remove.add_argument("tg_id", type=int)
    commands.add_parser("seed", help="импортировать тайтлы из репозитория, которых нет в базе")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
