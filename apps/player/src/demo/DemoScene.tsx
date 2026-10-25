import { SceneRunner, type Effect } from "@storymaker/engine";
import { VnScene } from "@storymaker/vn-renderer";
import { useEffect, useState } from "react";

import { demoAssets, demoCharacters, demoRegistry } from "./assets";
import source from "./demo.ink?raw";

// Состояние, как будто его прислал сервер: вода в инвентаре и высокая симпатия,
// чтобы были видны все три варианта выбора.
const SNAPSHOT = { items: { water_bottle: 1 }, affection: { anna: 25 } };

type State =
  | { kind: "compiling" }
  | { kind: "error"; messages: string[] }
  | { kind: "playing"; runner: SceneRunner }
  | { kind: "done"; effects: Effect[] };

function describe(effect: Effect): string {
  switch (effect.op) {
    case "affection":
      return `Симпатия ${effect.character}: ${effect.delta > 0 ? "+" : ""}${effect.delta}`;
    case "take":
      return `Отдано: ${effect.item}`;
    case "give":
      return `Получено: ${effect.item}`;
    case "flag":
      return `Флаг ${effect.flag}`;
    case "start_quest":
      return `Новый квест: ${effect.quest}`;
    default:
      return JSON.stringify(effect);
  }
}

export function DemoScene({ playerName, onExit }: { playerName?: string; onExit(): void }) {
  const [state, setState] = useState<State>({ kind: "compiling" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // Компилятор ink тяжёлый, поэтому грузится отдельным чанком только для демо.
    // В бою сцены будут приходить с сервера уже скомпилированными.
    void import("@storymaker/engine/compile").then(({ compileScene }) => {
      if (cancelled) {
        return;
      }
      const result = compileScene(source, demoRegistry);
      setState(
        result.scene
          ? { kind: "playing", runner: new SceneRunner(result.scene.json, SNAPSHOT) }
          : {
              kind: "error",
              messages: result.diagnostics.map((d) => `строка ${d.line ?? "?"}: ${d.message}`),
            },
      );
    });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  switch (state.kind) {
    case "compiling":
      return <main className="screen muted">Готовим сцену…</main>;
    case "error":
      return (
        <main className="screen">
          <h1>Сцена не скомпилировалась</h1>
          {state.messages.map((message) => (
            <p key={message} className="muted">
              {message}
            </p>
          ))}
        </main>
      );
    case "playing":
      return (
        <VnScene
          runner={state.runner}
          assets={demoAssets}
          characters={demoCharacters}
          playerName={playerName}
          onEnd={(effects) => setState({ kind: "done", effects })}
        />
      );
    case "done":
      return (
        <main className="screen">
          <h1>Сцена закончилась</h1>
          <p className="muted">Эти изменения отправились бы на сервер:</p>
          <ul className="effects">
            {state.effects.map((effect) => (
              <li key={JSON.stringify(effect)}>{describe(effect)}</li>
            ))}
          </ul>
          <div className="actions">
            <button type="button" onClick={() => setAttempt((n) => n + 1)}>
              Сыграть ещё раз
            </button>
            <button type="button" className="secondary" onClick={onExit}>
              Назад
            </button>
          </div>
        </main>
      );
  }
}
