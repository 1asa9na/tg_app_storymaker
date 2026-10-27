import io
import math
import struct
import wave

import pytest
from PIL import Image

from storymaker_api.assets import (
    AssetError,
    build_manifest,
    parse_name,
    process,
    referenced,
)


def png(size: tuple[int, int], mode: str = "RGB") -> bytes:
    """Картинка нужного размера; у RGBA прозрачный фон и непрозрачная «фигура» в центре."""
    buffer = io.BytesIO()
    if mode == "RGBA":
        image = Image.new("RGBA", size, (0, 0, 0, 0))
        w, h = size
        image.paste((200, 80, 120, 255), (w // 4, h // 4, w * 3 // 4, h))
    else:
        image = Image.new(mode, size, (90, 60, 140))
    image.save(buffer, "PNG")
    return buffer.getvalue()


def wav(seconds: float) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(44100)
        samples = (int(8000 * math.sin(i / 20)) for i in range(int(44100 * seconds)))
        file.writeframes(b"".join(struct.pack("<h", s) for s in samples))
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("filename", "kind", "key"),
    [
        ("bg_gym.png", "background", "gym"),
        ("bg_cafe_evening.png", "background", "cafe_evening"),
        ("anna_smirk.png", "sprite", "anna_smirk"),
        ("item_rose.png", "icon", "item_rose"),
        ("map_city_map.png", "map", "city_map"),
        ("cover_demo.png", "cover", "demo"),
        ("music_calm.wav", "music", "calm"),
        ("sfx_door_slam.mp3", "sfx", "door_slam"),
        ("backgrounds/bg_park.PNG", "background", "park"),
    ],
)
def test_names_follow_the_asset_spec(filename: str, kind: str, key: str) -> None:
    name = parse_name(filename)

    assert (name.kind, name.key) == (kind, key)


@pytest.mark.parametrize(
    "filename", ["Bg_gym.png", "gym.png", "bg_gym.wav", "music_calm.png", "notes.txt", "bg_.png"]
)
def test_bad_names_are_refused(filename: str) -> None:
    with pytest.raises(AssetError):
        parse_name(filename)


def test_background_gets_two_screen_sizes() -> None:
    result = process(parse_name("bg_gym.png"), png((1440, 2560)))

    sizes = {v.name: Image.open(io.BytesIO(v.data)).size for v in result.variants}
    assert sizes == {"1080": (1080, 1920), "720": (720, 1280)}
    assert result.warnings == []


def test_small_or_wrong_shape_background_warns() -> None:
    result = process(parse_name("bg_gym.png"), png((1000, 1500)))

    assert any("меньше 1080×1920" in w for w in result.warnings)
    assert any("не 9:16" in w for w in result.warnings)
    with pytest.raises(AssetError):
        process(parse_name("bg_gym.png"), png((500, 900)))


def test_sprite_keeps_alpha_and_warns_without_it() -> None:
    result = process(parse_name("anna_smirk.png"), png((1000, 2400), "RGBA"))
    opaque = process(parse_name("anna_happy.png"), png((1000, 2400)))

    image = Image.open(io.BytesIO(result.variants[0].data))
    assert image.mode == "RGBA"
    assert image.size == (750, 1800)
    assert any("прозрачности" in w for w in opaque.warnings)


def test_audio_becomes_aac() -> None:
    result = process(parse_name("music_calm.wav"), wav(1))

    assert [(v.name, v.extension, v.content_type) for v in result.variants] == [
        ("aac", "m4a", "audio/mp4")
    ]
    with pytest.raises(AssetError):
        process(parse_name("sfx_x.wav"), b"not a sound")


def test_referenced_assets_from_data_and_scene_tags() -> None:
    sections = {
        "locations": {"gym": {"name": "Зал", "background": "gym"}},
        "map": {"image": "city_map"},
        "items": {"rose": {"name": "Роза", "icon": "item_rose"}},
        "characters": {"anna": {"name": "Анна", "emotions": ["neutral", "happy"]}},
    }
    scene = (
        "# bg: rooftop\n# music: calm\nПривет # show: anna smirk left\n# music: stop\n# sfx: door"
    )

    needed = referenced(sections, {"intro": scene})

    assert needed == {
        ("background", "gym"),
        ("background", "rooftop"),
        ("map", "city_map"),
        ("icon", "item_rose"),
        ("sprite", "anna_neutral"),
        ("sprite", "anna_happy"),
        ("sprite", "anna_smirk"),
        ("music", "calm"),
        ("sfx", "door"),
    }


def test_manifest_groups_sprites_by_character() -> None:
    manifest = build_manifest(
        [
            ("background", "gym", {"1080": "t/x/a.1080.webp", "720": "t/x/a.720.webp"}),
            ("sprite", "anna_smirk", {"1800": "t/x/b.1800.webp"}),
            ("music", "calm", {"aac": "t/x/c.aac.m4a"}),
        ]
    )

    assert manifest == {
        "background": {"gym": {"1080": "/assets/t/x/a.1080.webp", "720": "/assets/t/x/a.720.webp"}},
        "sprite": {"anna": {"smirk": {"1800": "/assets/t/x/b.1800.webp"}}},
        "music": {"calm": "/assets/t/x/c.aac.m4a"},
    }
