import shutil
from pathlib import Path
from typing import Any

import pytest

from storymaker_api.game.loader import load_title
from storymaker_api.game.scenes import ENGINE_DIR, ScenePlayer
from storymaker_api.game.schema import Title
from storymaker_api.game.simulator import Settings, Simulation, parse_goal, report
from tests.game.conftest import TITLE

DEMO = Path(__file__).parents[4] / "content" / "titles" / "demo"
HAS_NODE = shutil.which("node") is not None and (ENGINE_DIR / "node_modules" / "inkjs").exists()


class SilentScenes:
    """Сцены без эффектов: проверяем только игровой цикл."""

    def play(self, scene_json: str, snapshot: dict[str, Any], strategy: str, seed: int) -> list:
        return []


def test_simulation_is_deterministic_and_finishes() -> None:
    title = Title.model_validate(TITLE)
    settings = Settings(players=5, seed=7)

    first = Simulation(title, SilentScenes(), settings).run()
    second = Simulation(title, SilentScenes(), settings).run()

    assert [run.day_reached_at for run in first] == [run.day_reached_at for run in second]
    assert all(run.final and run.final.finished for run in first)
    assert not any(run.stuck for run in first)


def test_report_lists_days_scenes_and_quests() -> None:
    title = Title.model_validate(TITLE)
    settings = Settings(players=3)

    text = report(title, settings, Simulation(title, SilentScenes(), settings).run())

    assert text.startswith("# Симуляция «Тест»")
    assert "| 3 | 100% |" in text
    assert "| anna_meet |" in text
    assert "| anna_trust |" in text


def test_goal_strategy_moves_its_metric() -> None:
    title = Title.model_validate(TITLE)

    def fitness(strategy: str) -> list[float]:
        settings = Settings(players=8, strategy=strategy, seed=5)
        runs = Simulation(title, SilentScenes(), settings).run()
        return [run.metric_by_day[0] for run in runs]

    high = fitness("goal:stat.fitness:max")
    low = fitness("goal:stat.fitness:min")

    assert min(high) > max(low)
    assert max(low) == 0  # тренировка — единственный способ поднять форму, её избегают


def test_goal_report_and_validation() -> None:
    title = Title.model_validate(TITLE)
    settings = Settings(players=3, strategy="goal:resource.money:max")

    text = report(title, settings, Simulation(title, SilentScenes(), settings).run())

    assert "## Цель: Деньги — максимизация" in text
    assert "| к концу |" in text
    with pytest.raises(ValueError, match=r"нет метрики stat\.nope"):
        parse_goal("goal:stat.nope:max", title)
    with pytest.raises(ValueError, match="max или"):
        parse_goal("goal:stat.fitness:up", title)


@pytest.mark.skipif(not HAS_NODE, reason="нужен Node.js и pnpm install в packages/engine")
def test_demo_title_loads_and_plays_with_real_scenes() -> None:
    result = load_title(DEMO)
    assert result.errors == []
    assert result.title is not None

    settings = Settings(players=20, strategy="romance:anna", seed=3)
    with ScenePlayer() as player:
        runs = Simulation(result.title, player, settings).run()

    assert all(run.final and run.final.finished for run in runs)
    assert all({"intro", "anna_meet"} <= run.scenes for run in runs)
    assert max(run.final.affection["anna"] for run in runs if run.final) > 20
