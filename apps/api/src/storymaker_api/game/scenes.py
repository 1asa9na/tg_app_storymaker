"""Мост к TypeScript-движку сцен (packages/engine): компиляция и проигрывание через Node."""

import json
import os
import subprocess
from pathlib import Path
from types import TracebackType
from typing import Any, Self

ENGINE_DIR = Path(
    os.environ.get("STORYMAKER_ENGINE_DIR")
    or Path(__file__).resolve().parents[5] / "packages" / "engine"
)


class EngineUnavailableError(RuntimeError):
    pass


def _node(script: str) -> list[str]:
    path = ENGINE_DIR / "src" / script
    if not path.exists():
        raise EngineUnavailableError(f"не найден {path}; задайте STORYMAKER_ENGINE_DIR")
    return ["node", str(path)]


def compile_scenes(sources: dict[str, str], registry: dict[str, Any]) -> dict[str, Any]:
    """Компилирует сцены: {"ok", "scenes": {key: {"json", "effects"}}, "diagnostics": {...}}."""
    try:
        result = subprocess.run(
            _node("cli.ts"),
            input=json.dumps({"scenes": sources, "registry": registry}),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except FileNotFoundError:
        raise EngineUnavailableError("не найден node: для сцен нужен Node.js 22.18+") from None
    if result.returncode != 0:
        raise EngineUnavailableError(f"компилятор сцен упал: {result.stderr.strip()}")
    return json.loads(result.stdout)


class ScenePlayer:
    """Проигрывает сцены в одном долгоживущем процессе Node (play-worker.ts)."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 0

    def __enter__(self) -> Self:
        try:
            self._process = subprocess.Popen(
                _node("play-worker.ts"),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            raise EngineUnavailableError("не найден node: для сцен нужен Node.js 22.18+") from None
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._process is not None:
            assert self._process.stdin is not None
            self._process.stdin.close()
            self._process.wait(timeout=10)

    def play(
        self, scene_json: str, snapshot: dict[str, Any], strategy: str, seed: int
    ) -> list[dict[str, Any]]:
        """Проигрывает сцену до конца и возвращает её эффекты в формате движка сцен."""
        assert self._process is not None and self._process.stdin and self._process.stdout
        self._next_id += 1
        request = {
            "id": self._next_id,
            "json": scene_json,
            "snapshot": snapshot,
            "strategy": strategy,
            "seed": seed,
        }
        self._process.stdin.write(json.dumps(request) + "\n")
        response = json.loads(self._process.stdout.readline())
        if "error" in response:
            raise RuntimeError(f"сцена упала: {response['error']}")
        return response["effects"]
