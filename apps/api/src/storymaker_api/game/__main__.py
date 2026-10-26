"""Инструменты геймдизайнера.

uv run python -m storymaker_api.game check ../../content/titles/demo
uv run python -m storymaker_api.game simulate ../../content/titles/demo --players 200
"""

import argparse
import sys
from pathlib import Path

from storymaker_api.game.loader import load_title
from storymaker_api.game.scenes import EngineUnavailableError, ScenePlayer
from storymaker_api.game.simulator import Settings, Simulation, report


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m storymaker_api.game")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="проверить тайтл: схемы, ссылки, сцены")
    check.add_argument("title", type=Path)

    simulate = commands.add_parser("simulate", help="прогнать симулятор баланса")
    simulate.add_argument("title", type=Path)
    simulate.add_argument("--players", type=int, default=100)
    simulate.add_argument("--strategy", default="random", help="random или romance:<персонаж>")
    simulate.add_argument("--scene-strategy", default="free", choices=["free", "random", "first"])
    simulate.add_argument("--session-gap", type=float, default=4, help="часов между сессиями")
    simulate.add_argument("--hours", type=float, default=24 * 14, help="горизонт, часов")
    simulate.add_argument("--seed", type=int, default=1)

    args = parser.parse_args()
    try:
        result = load_title(args.title)
    except EngineUnavailableError as error:
        print(f"✗ {error}", file=sys.stderr)
        return 2
    for warning in result.warnings:
        print(f"⚠ {warning}", file=sys.stderr)
    for error in result.errors:
        print(f"✗ {error}", file=sys.stderr)
    if result.errors or result.title is None:
        print(f"Ошибок: {len(result.errors)}", file=sys.stderr)
        return 1

    if args.command == "check":
        print(f"✓ {result.title.config.name}: ошибок нет, предупреждений: {len(result.warnings)}")
        return 0

    settings = Settings(
        players=args.players,
        strategy=args.strategy,
        scene_strategy=args.scene_strategy,
        session_gap_hours=args.session_gap,
        horizon_hours=args.hours,
        seed=args.seed,
    )
    if settings.strategy.startswith("romance:"):
        focus = settings.strategy.removeprefix("romance:")
        if focus not in result.title.characters:
            print(f"✗ персонажа «{focus}» нет в тайтле", file=sys.stderr)
            return 1
    with ScenePlayer() as player:
        runs = Simulation(result.title, player, settings).run()
    print(report(result.title, settings, runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
