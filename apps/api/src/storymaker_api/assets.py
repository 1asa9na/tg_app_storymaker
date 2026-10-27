"""Ассеты тайтлов: разбор имён файлов, варианты для телефона, хранилище, манифест сборки.

Требования к исходникам и имена файлов — docs/ASSETS.md. Исходник уходит в бакет originals
(Supabase), варианты — на диск сервера (/srv/assets, их раздаёт Caddy по /assets/…) и копией
в бакет assets. Имена вариантов содержат хеш исходника: файлы не перезаписываются и
кэшируются навсегда, а сборка фиксирует конкретные версии — откат возвращает и старый арт.
"""

import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import av
import boto3
from av.error import FFmpegError
from botocore.config import Config
from PIL import Image, ImageOps, UnidentifiedImageError

from storymaker_api.config import Settings

Kind = Literal[
    "background", "map", "sprite", "icon", "achievement", "avatar", "cover", "music", "sfx"
]

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
AUDIO_EXTENSIONS = {"wav", "mp3", "m4a", "ogg", "flac"}
MAX_BYTES = 40_000_000
IMMUTABLE = "public, max-age=31536000, immutable"

KEY = r"[a-z][a-z0-9_]*"
#: Префикс имени файла → вид ассета (docs/ASSETS.md §6.2). Иконка предмета хранит ключ
#: целиком (item_rose): так он записан в items.yaml.
PREFIXES: dict[str, Kind] = {
    "bg_": "background",
    "map_": "map",
    "ach_": "achievement",
    "avatar_": "avatar",
    "cover_": "cover",
    "music_": "music",
    "sfx_": "sfx",
}
AUDIO_KINDS = {"music", "sfx"}


class AssetError(ValueError):
    pass


@dataclass(frozen=True)
class AssetName:
    kind: Kind
    key: str
    extension: str

    @property
    def character(self) -> str:
        """Спрайт anna_smirk: персонаж anna (в ключе персонажа нет «_»)."""
        return self.key.split("_", 1)[0]

    @property
    def emotion(self) -> str:
        return self.key.split("_", 1)[1]


def parse_name(filename: str) -> AssetName:
    """bg_gym.png → фон gym; anna_smirk.png → спрайт; item_rose.png → иконка item_rose."""
    name = Path(filename).name
    stem, _, extension = name.rpartition(".")
    extension = extension.lower()
    if not stem or extension not in IMAGE_EXTENSIONS | AUDIO_EXTENSIONS:
        raise AssetError(f"{name}: нужен PNG, JPG или WebP для картинок, WAV или MP3 для звука")
    if not re.fullmatch(KEY, stem):
        raise AssetError(f"{name}: имя — латиница в нижнем регистре, цифры и _ (ASSETS.md §6.1)")
    kind: Kind
    if stem.startswith("item_"):
        kind, key = "icon", stem
    else:
        prefix = next((p for p in PREFIXES if stem.startswith(p)), None)
        if prefix:
            kind, key = PREFIXES[prefix], stem.removeprefix(prefix)
        elif "_" in stem:
            kind, key = "sprite", stem
        else:
            raise AssetError(
                f"{name}: непонятно, что это. Шаблоны: bg_<фон>, <персонаж>_<эмоция>, "
                "item_<предмет>, map_<карта>, cover_<тайтл>, music_<трек>, sfx_<звук>"
            )
    if not re.fullmatch(KEY, key):
        raise AssetError(f"{name}: пустой или неправильный ключ после префикса")
    audio = kind in AUDIO_KINDS
    if audio != (extension in AUDIO_EXTENSIONS):
        expected = "звук (WAV или MP3)" if audio else "картинка (PNG, JPG или WebP)"
        raise AssetError(f"{name}: по имени это {LABELS[kind]}, нужен файл: {expected}")
    return AssetName(kind, key, extension)


# ── Обработка ───────────────────────────────────────────────────────────


@dataclass
class Variant:
    name: str
    data: bytes
    content_type: str
    extension: str


@dataclass
class Processed:
    width: int | None
    height: int | None
    variants: list[Variant]
    warnings: list[str] = field(default_factory=list)


#: Вид → варианты (имя, ширина, высота) и лимит веса варианта (docs/ASSETS.md §3.2).
SCREEN = [("1080", 1080, 1920), ("720", 720, 1280)]
LIMITS = {
    "background": 400_000,
    "map": 400_000,
    "sprite": 300_000,
    "icon": 30_000,
    "achievement": 30_000,
    "avatar": 30_000,
    "cover": 150_000,
}


def _webp(image: Image.Image, quality: int = 80) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "WEBP", quality=quality, method=6)
    return buffer.getvalue()


def process_image(name: AssetName, data: bytes) -> Processed:
    try:
        source = Image.open(io.BytesIO(data))
        source.load()
    except (UnidentifiedImageError, OSError):
        raise AssetError("файл не открывается как картинка") from None
    width, height = source.size
    warnings: list[str] = []
    variants: list[Variant] = []

    def add(label: str, image: Image.Image, quality: int = 80) -> None:
        variants.append(Variant(label, _webp(image, quality), "image/webp", "webp"))

    match name.kind:
        case "background" | "map":
            if width < 720 or height < 1280:
                raise AssetError(f"{width}×{height}: нужно не меньше 1080×1920 (лучше 1440×2560)")
            if width < 1080 or height < 1920:
                warnings.append(f"{width}×{height} меньше 1080×1920 — на телефоне будет мыло")
            if abs(width / height - 9 / 16) > 0.02:
                warnings.append(f"{width}×{height} — не 9:16, края обрежутся")
            rgb = ImageOps.exif_transpose(source).convert("RGB")
            for label, w, h in SCREEN:
                add(label, ImageOps.fit(rgb, (w, h), Image.Resampling.LANCZOS))
        case "sprite":
            if source.mode not in ("RGBA", "LA", "PA") and "transparency" not in source.info:
                warnings.append("нет прозрачности — спрайт закроет фон прямоугольником")
            rgba = source.convert("RGBA")
            for label in ("1800", "1200"):
                target = min(int(label), height)
                scaled = rgba.resize(
                    (round(width * target / height), target), Image.Resampling.LANCZOS
                )
                add(label, scaled, 85)
        case "icon" | "achievement" | "avatar":
            if width != height:
                warnings.append(f"{width}×{height} — не квадрат, по краям будет прозрачно")
            canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
            icon = ImageOps.contain(source.convert("RGBA"), (256, 256), Image.Resampling.LANCZOS)
            canvas.paste(icon, ((256 - icon.width) // 2, (256 - icon.height) // 2))
            add("256", canvas, 85)
        case "cover":
            rgb = ImageOps.exif_transpose(source).convert("RGB")
            add("full", ImageOps.fit(rgb, (600, 800), Image.Resampling.LANCZOS))
            add("preview", ImageOps.fit(rgb, (300, 400), Image.Resampling.LANCZOS))
        case _:
            raise AssetError("это не картинка")
    limit = LIMITS[name.kind]
    for variant in variants:
        if len(variant.data) > limit:
            warnings.append(
                f"вариант {variant.name}: {len(variant.data) // 1000} КБ при лимите "
                f"{limit // 1000} КБ — шум и зерно сильно увеличивают вес"
            )
    return Processed(width, height, variants, warnings)


def process_audio(name: AssetName, data: bytes) -> Processed:
    """Любой звук → AAC в .m4a: музыка 128 кбит/с, эффекты 96 кбит/с, 44,1 кГц стерео."""
    bitrate = 128_000 if name.kind == "music" else 96_000
    output = io.BytesIO()
    try:
        with av.open(io.BytesIO(data), "r") as source:
            if not source.streams.audio:
                raise AssetError("в файле нет звука")
            with av.open(output, "w", format="ipod") as target:
                stream = target.add_stream("aac", rate=44100)
                stream.bit_rate = bitrate
                stream.layout = "stereo"
                resampler = av.AudioResampler(format="fltp", layout="stereo", rate=44100)
                for frame in source.decode(audio=0):
                    for resampled in resampler.resample(frame):
                        target.mux(stream.encode(resampled))
                for resampled in resampler.resample(None):
                    target.mux(stream.encode(resampled))
                target.mux(stream.encode(None))
    except FFmpegError:
        raise AssetError("файл не открывается как звук") from None
    variant = Variant("aac", output.getvalue(), "audio/mp4", "m4a")
    warnings = []
    if name.kind == "sfx" and len(variant.data) > 100_000:
        warnings.append(f"{len(variant.data) // 1000} КБ — эффект длиннее 2–3 с?")
    return Processed(None, None, [variant], warnings)


def process(name: AssetName, data: bytes) -> Processed:
    if len(data) > MAX_BYTES:
        raise AssetError(f"файл больше {MAX_BYTES // 1_000_000} МБ")
    if name.kind in AUDIO_KINDS:
        return process_audio(name, data)
    return process_image(name, data)


# ── Хранилище ───────────────────────────────────────────────────────────


class Storage:
    """Варианты — на диск (их раздаёт Caddy) и копией в бакет assets; исходники — в originals.

    Без настроек S3 (локально, в тестах) работает только диск.
    """

    def __init__(self, settings: Settings) -> None:
        self.root = settings.assets_dir
        self.settings = settings
        self.s3: Any = None
        secret = settings.s3_secret_access_key
        if settings.s3_endpoint_url and settings.s3_access_key_id and secret:
            self.s3 = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url,
                region_name=settings.s3_region,
                aws_access_key_id=settings.s3_access_key_id,
                aws_secret_access_key=secret.get_secret_value(),
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )

    def put_original(self, path: str, data: bytes) -> None:
        if self.s3 is not None:
            self.s3.put_object(Bucket=self.settings.s3_bucket_originals, Key=path, Body=data)

    def put_variant(self, path: str, variant: Variant) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(variant.data)
        if self.s3 is not None:
            self.s3.put_object(
                Bucket=self.settings.s3_bucket_assets,
                Key=path,
                Body=variant.data,
                ContentType=variant.content_type,
                CacheControl=IMMUTABLE,
            )


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:32]


def variant_path(slug: str, digest: str, variant: Variant) -> str:
    return f"t/{slug}/{digest[:2]}/{digest}.{variant.name}.{variant.extension}"


def original_path(slug: str, name: AssetName, digest: str) -> str:
    return f"{slug}/{name.kind}/{name.key}/{digest}.{name.extension}"


# ── Какие ассеты нужны тайтлу ───────────────────────────────────────────

_TAG = re.compile(r"^\s*#\s*(bg|show|music|sfx)\s*:\s*(.+?)\s*$", re.MULTILINE)


def referenced(sections: dict[str, Any], scenes: dict[str, str]) -> set[tuple[Kind, str]]:
    """Ассеты, на которые ссылаются данные и сцены: (вид, ключ)."""
    needed: set[tuple[Kind, str]] = set()
    for location in (sections.get("locations") or {}).values():
        if isinstance(location, dict) and isinstance(location.get("background"), str):
            needed.add(("background", location["background"]))
    image = (sections.get("map") or {}).get("image")
    if isinstance(image, str):
        needed.add(("map", image))
    for item in (sections.get("items") or {}).values():
        if isinstance(item, dict) and isinstance(item.get("icon"), str):
            needed.add(("icon", item["icon"]))
    for character, data in (sections.get("characters") or {}).items():
        emotions = data.get("emotions") if isinstance(data, dict) else None
        for emotion in emotions if isinstance(emotions, list) else []:
            needed.add(("sprite", f"{character}_{emotion}"))
    for source in scenes.values():
        # Теги стоят и в начале строки, и в конце реплики: «Привет # show: anna happy».
        for line in source.splitlines():
            for tag in line.split("#")[1:]:
                match = _TAG.match("#" + tag)
                if not match:
                    continue
                kind, value = match.group(1), match.group(2).split()
                if kind == "bg" and value:
                    needed.add(("background", value[0]))
                elif kind == "show" and len(value) >= 2:
                    needed.add(("sprite", f"{value[0]}_{value[1]}"))
                elif kind in ("music", "sfx") and value and value[0] != "stop":
                    needed.add(("music" if kind == "music" else "sfx", value[0]))
    return needed


LABELS: dict[Kind, str] = {
    "background": "фон",
    "map": "карта",
    "sprite": "спрайт",
    "icon": "иконка",
    "achievement": "иконка достижения",
    "avatar": "аватар",
    "cover": "обложка",
    "music": "музыка",
    "sfx": "звук",
}


def file_name(kind: Kind, key: str) -> str:
    """Какой файл ждём от художника для ассета."""
    prefix = {v: k for k, v in PREFIXES.items()}.get(kind, "")
    extension = "wav" if kind in AUDIO_KINDS else "png"
    return f"{prefix}{key}.{extension}"


def manifest_entry(kind: Kind, variants: dict[str, str], base: str = "/assets/") -> Any:
    urls = {name: base + path for name, path in variants.items()}
    return urls["aac"] if kind in AUDIO_KINDS else urls


def build_manifest(versions: list[tuple[Kind, str, dict[str, str]]]) -> dict[str, Any]:
    """Манифест сборки для плеера: вид → ключ → адреса вариантов (у звука — один адрес).

    Спрайты — персонаж → эмоция → варианты.
    """
    manifest: dict[str, Any] = {}
    for kind, key, variants in sorted(versions):
        entry = manifest_entry(kind, variants)
        if kind == "sprite":
            character, emotion = key.split("_", 1)
            manifest.setdefault("sprite", {}).setdefault(character, {})[emotion] = entry
        else:
            manifest.setdefault(kind, {})[key] = entry
    return manifest


def dump_manifest(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, sort_keys=True)
