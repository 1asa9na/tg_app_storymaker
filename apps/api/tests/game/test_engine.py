from datetime import timedelta

import pytest

from storymaker_api.game.engine import (
    ActionError,
    DoActivity,
    Engine,
    Gift,
    Go,
    SceneComplete,
    Sleep,
    Use,
)
from storymaker_api.game.state import GameState
from tests.game.conftest import NOW


def at_evening(engine: Engine) -> GameState:
    """Новая игра, сдвинутая на вечер первого дня."""
    state = engine.new_game(NOW)
    state = engine.apply(state, DoActivity(type="activity", id="rest"), NOW).state
    return engine.apply(state, DoActivity(type="activity", id="rest"), NOW).state


def test_new_game_starts_from_config(engine: Engine) -> None:
    state = engine.new_game(NOW)

    assert (state.day, state.slot, state.location) == (1, 0, "home")
    assert state.resources["energy"].value == 50
    assert state.items == {"rose": 1}
    assert state.stats == {"fitness": 0}


def test_activity_spends_resources_applies_effects_and_advances_time(engine: Engine) -> None:
    state = engine.new_game(NOW)
    state = engine.apply(state, Go(type="go", location="gym"), NOW).state

    outcome = engine.apply(state, DoActivity(type="activity", id="workout"), NOW)

    assert outcome.state.slot == 1
    assert outcome.state.stats["fitness"] == 3
    assert outcome.xp == 5
    assert {(c.path, c.delta) for c in outcome.changes} == {
        ("resource.energy", -20),
        ("stat.fitness", 3),
    }
    assert outcome.scenes == ["first_workout"]


def test_pending_scene_blocks_other_actions(engine: Engine) -> None:
    state = engine.new_game(NOW)
    state = engine.apply(state, Go(type="go", location="gym"), NOW).state
    state = engine.apply(state, DoActivity(type="activity", id="workout"), NOW).state

    with pytest.raises(ActionError) as error:
        engine.apply(state, Go(type="go", location="home"), NOW)

    assert error.value.code == "scene_pending"


def test_scene_effects_are_checked_against_the_whitelist(engine: Engine) -> None:
    state = at_evening(engine)
    state = engine.apply(state, Go(type="go", location="gym"), NOW).state
    assert state.pending_scenes[0].scene == "anna_meet"
    assert state.flags["met_anna"] is True

    forged = {"op": "affection", "character": "anna", "delta": 100}
    with pytest.raises(ActionError) as error:
        engine.apply(
            state, SceneComplete(type="scene_complete", scene="anna_meet", effects=[forged]), NOW
        )
    honest = {"op": "affection", "character": "anna", "delta": 1}
    outcome = engine.apply(
        state, SceneComplete(type="scene_complete", scene="anna_meet", effects=[honest]), NOW
    )

    assert error.value.code == "effect_not_allowed"
    assert outcome.state.affection["anna"] == 1
    assert outcome.state.pending_scenes == []


def test_locked_location_and_activity_explain_why(engine: Engine) -> None:
    state = engine.new_game(NOW)

    assert engine.location_lock(state, "cafe") == "Сначала познакомьтесь с Анной"
    assert engine.location_lock(state, "gym") is None
    state = engine.apply(state, DoActivity(type="activity", id="rest"), NOW).state
    assert engine.location_lock(state, "gym") == "Открыто: утро, вечер"
    with pytest.raises(ActionError, match="Открыто: утро, вечер"):
        engine.apply(state, Go(type="go", location="gym"), NOW)


def test_schedule_places_characters_by_slot_and_weekday(engine: Engine) -> None:
    state = engine.new_game(NOW)
    assert engine.where_is(state, "anna") is None

    state = at_evening(engine)
    assert engine.where_is(state, "anna") == "gym"

    state = state.model_copy(update={"day": 2, "slot": 1})
    assert engine.where_is(state, "anna") == "cafe"


def test_activity_with_character_needs_them_present(engine: Engine) -> None:
    state = engine.new_game(NOW)
    state = engine.apply(state, Go(type="go", location="gym"), NOW).state

    assert engine.activity_lock(state, "talk") == "Анна сейчас не здесь"


def test_energy_regenerates_in_real_time(engine: Engine) -> None:
    state = engine.new_game(NOW)
    state = engine.apply(state, Go(type="go", location="gym"), NOW).state
    state = engine.apply(state, DoActivity(type="activity", id="workout"), NOW).state
    assert state.resources["energy"].value == 30

    later = engine.refresh(state, NOW + timedelta(minutes=33))
    full = engine.refresh(state, NOW + timedelta(hours=5))

    assert later.resources["energy"].value == 35
    assert later.resources["energy"].anchor == NOW + timedelta(minutes=30)
    assert full.resources["energy"].value == 50
    assert full.resources["energy"].anchor is None


def test_unaffordable_activity_is_locked(engine: Engine) -> None:
    state = engine.new_game(NOW)
    state.resources["energy"].value = 10
    state = engine.apply(state, Go(type="go", location="gym"), NOW).state

    assert engine.activity_lock(state, "workout") == "Не хватает: энергия (нужно 20)"


def test_gift_uses_character_preferences_once_per_day(engine: Engine) -> None:
    state = at_evening(engine)
    state = engine.apply(state, Go(type="go", location="gym"), NOW).state
    state = engine.apply(
        state, SceneComplete(type="scene_complete", scene="anna_meet", effects=[]), NOW
    ).state
    state.items["rose"] = 2

    outcome = engine.apply(state, Gift(type="gift", item="rose", character="anna"), NOW)
    with pytest.raises(ActionError) as error:
        engine.apply(outcome.state, Gift(type="gift", item="rose", character="anna"), NOW)

    assert outcome.state.affection["anna"] == 5
    assert outcome.state.items["rose"] == 1
    assert error.value.code == "gift_limit"


def test_quests_start_and_progress_from_conditions(engine: Engine) -> None:
    state = at_evening(engine)
    outcome = engine.apply(state, Go(type="go", location="gym"), NOW)
    assert outcome.quests == [("anna_trust", "active", "talk")]

    state = engine.apply(
        outcome.state, SceneComplete(type="scene_complete", scene="anna_meet", effects=[]), NOW
    ).state
    state.affection["anna"] = 3
    step = engine.apply(state, DoActivity(type="activity", id="talk"), NOW)
    assert step.quests == [("anna_trust", "active", "gift")]

    final = engine.apply(step.state, Gift(type="gift", item="rose", character="anna"), NOW)
    assert final.quests == [("anna_trust", "done", None)]
    assert final.xp == 50
    assert final.achievements == ["trusted"]
    assert final.state.quests["anna_trust"].status == "done"


def test_sleep_starts_a_new_day_and_the_title_ends(engine: Engine) -> None:
    state = engine.new_game(NOW)
    with pytest.raises(ActionError) as error:
        engine.apply(state, Sleep(type="sleep"), NOW)
    assert error.value.message == "Лечь спать можно: вечер"

    state = at_evening(engine)
    for day in (2, 3):
        outcome = engine.apply(state, Sleep(type="sleep"), NOW)
        assert (outcome.state.day, outcome.state.slot, outcome.new_day) == (day, 0, True)
        state = outcome.state.model_copy(update={"slot": 2})
    final = engine.apply(state, Sleep(type="sleep"), NOW)

    assert final.state.finished is True
    with pytest.raises(ActionError):
        engine.apply(final.state, Use(type="use", item="tea"), NOW)


def test_activities_roll_time_over_to_the_next_day(engine: Engine) -> None:
    state = at_evening(engine)
    state = engine.apply(state, Go(type="go", location="gym"), NOW).state
    state = engine.apply(
        state, SceneComplete(type="scene_complete", scene="anna_meet", effects=[]), NOW
    ).state

    outcome = engine.apply(state, DoActivity(type="activity", id="workout"), NOW)

    assert (outcome.state.day, outcome.state.slot) == (2, 0)
    assert outcome.state.location == "home"
    assert outcome.new_day is True


def test_consumables_apply_their_effects(engine: Engine) -> None:
    state = engine.new_game(NOW)
    state.items["tea"] = 1
    state.resources["energy"].value = 20

    outcome = engine.apply(state, Use(type="use", item="tea"), NOW)

    assert outcome.state.resources["energy"].value == 35
    assert outcome.state.items["tea"] == 0


def test_activities_lock_when_their_location_closes(engine: Engine) -> None:
    state = engine.new_game(NOW)
    state = engine.apply(state, Go(type="go", location="gym"), NOW).state
    state = engine.apply(state, DoActivity(type="activity", id="workout"), NOW).state
    state = engine.apply(
        state, SceneComplete(type="scene_complete", scene="first_workout", effects=[]), NOW
    ).state

    assert state.location == "gym"
    assert engine.activity_lock(state, "workout") == "Открыто: утро, вечер"
