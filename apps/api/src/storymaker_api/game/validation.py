"""Проверка ссылок между сущностями тайтла: всё, что схема по отдельности проверить не может."""

from storymaker_api.game.conditions import check_condition, check_effects
from storymaker_api.game.schema import Title


def check_title(title: Title) -> tuple[list[str], list[str]]:
    """Возвращает (ошибки, предупреждения). С ошибками тайтл не публикуется."""
    errors: list[str] = []
    warnings: list[str] = []
    slots = set(title.slot_ids)
    config = title.config
    week = set(config.time.week or [])

    def unknown(values: list[str] | None, known: set[str] | dict, noun: str, where: str) -> None:
        for value in values or []:
            if value not in known:
                errors.append(f"{where}: {noun} «{value}» нет в тайтле")

    unknown(config.time.sleep_from, slots, "слота", "title.time.sleep_from")
    if config.start.location:
        unknown([config.start.location], title.locations, "локации", "title.start.location")
    unknown(list(config.start.items), title.items, "предмета", "title.start.items")

    for key, character in title.characters.items():
        where = f"characters.{key}"
        unknown(list(character.gifts), title.items, "предмета", f"{where}.gifts")
        thresholds = [level.at for level in character.levels]
        if thresholds != sorted(thresholds):
            errors.append(f"{where}.levels: пороги должны идти по возрастанию")
        for index, entry in enumerate(character.schedule):
            at = f"{where}.schedule[{index}]"
            unknown([entry.location], title.locations, "локации", at)
            unknown(entry.slots, slots, "слота", f"{at}.slots")
            if entry.weekdays and not week:
                errors.append(f"{at}.weekdays: в title.yaml не задана неделя (time.week)")
            else:
                unknown(entry.weekdays, week, "дня недели", f"{at}.weekdays")
            errors += check_condition(entry.when, title, f"{at}.when")

    unknown(list(title.map.points), title.locations, "локации", "map.points")

    for key, location in title.locations.items():
        where = f"locations.{key}"
        unknown(location.slots, slots, "слота", f"{where}.slots")
        errors += check_condition(location.visible_when, title, f"{where}.visible_when")
        errors += check_condition(location.unlock_when, title, f"{where}.unlock_when")

    for key, activity in title.activities.items():
        where = f"activities.{key}"
        location = title.locations.get(activity.location)
        if location is None:
            errors.append(f"{where}.location: локации «{activity.location}» нет в тайтле")
        unknown(activity.slots, slots, "слота", f"{where}.slots")
        if location and location.slots and activity.slots:
            closed = [slot for slot in activity.slots if slot not in location.slots]
            if closed:
                errors.append(
                    f"{where}.slots: локация «{activity.location}» закрыта в {', '.join(closed)}"
                )
        unknown(list(activity.cost.resources), config.resources, "ресурса", f"{where}.cost")
        if activity.with_character:
            unknown(
                [activity.with_character], title.characters, "персонажа", f"{where}.with_character"
            )
        errors += check_condition(activity.requires, title, f"{where}.requires")
        errors += check_effects(activity.effects, title, f"{where}.effects")

    for key, item in title.items.items():
        if not item.use.is_empty() and item.kind != "consumable":
            errors.append(
                f"items.{key}.use: эффекты использования бывают только у kind: consumable"
            )
        errors += check_effects(item.use, title, f"items.{key}.use")

    for key, quest in title.quests.items():
        where = f"quests.{key}"
        errors += check_condition(quest.start_when, title, f"{where}.start_when")
        stage_ids = [stage.id for stage in quest.stages]
        if len(stage_ids) != len(set(stage_ids)):
            errors.append(f"{where}.stages: id этапов должны быть уникальными")
        for stage in quest.stages:
            errors += check_condition(
                stage.complete_when, title, f"{where}.{stage.id}.complete_when"
            )
            errors += check_effects(stage.effects, title, f"{where}.{stage.id}.effects")
        errors += check_effects(quest.rewards, title, f"{where}.rewards")

    triggered_scenes: set[str] = set()
    for key, event in title.events.items():
        where = f"events.{key}"
        if event.trigger.activity:
            unknown([event.trigger.activity], title.activities, "занятия", f"{where}.trigger")
        if event.trigger.location:
            unknown([event.trigger.location], title.locations, "локации", f"{where}.trigger")
        if event.scene:
            triggered_scenes.add(event.scene)
            unknown([event.scene], title.scenes, "сцены", f"{where}.scene")
        errors += check_condition(event.when, title, f"{where}.when")
        errors += check_effects(event.effects, title, f"{where}.effects")

    for scene in title.scenes:
        if scene not in triggered_scenes:
            warnings.append(f"scenes/{scene}.ink: сцену не запускает ни одно событие")

    for key in title.locations:
        if key not in title.map.points and title.map.image:
            warnings.append(f"map.points: у локации «{key}» нет точки на карте")
        if not any(activity.location == key for activity in title.activities.values()):
            warnings.append(f"locations.{key}: в локации нет ни одного занятия")

    return errors, warnings
