import { SceneRunner, type Effect } from "@storymaker/engine";
import { VnScene, type AssetResolver, type CharacterInfo } from "@storymaker/vn-renderer";
import { useEffect, useMemo, useState } from "react";

import type { GameClient, GameData, SaveState } from "./types.ts";

interface Props {
  client: GameClient;
  game: GameData;
  scene: string;
  state: SaveState;
  assets: AssetResolver;
  playerName?: string;
  onEnd(effects: Effect[]): void;
}

type Load = { kind: "loading" } | { kind: "error" } | { kind: "ready"; runner: SceneRunner };

/** Сцена из очереди: скомпилированный JSON с сервера, снимок состояния для условий в сцене. */
export function SceneLayer({ client, game, scene, state, assets, playerName, onEnd }: Props) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    client.scene(scene).then(
      ({ json }) => {
        if (cancelled) return;
        const snapshot = {
          affection: state.affection,
          items: state.items,
          flags: state.flags,
          stats: state.stats,
          globalLevel: state.global_level,
        };
        setLoad({ kind: "ready", runner: new SceneRunner(json, snapshot) });
      },
      () => !cancelled && setLoad({ kind: "error" }),
    );
    return () => {
      cancelled = true;
    };
    // Состояние берётся на момент открытия сцены: эффекты применяются только в конце.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, scene, attempt]);

  const characters = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(game.characters).map(([key, c]): [string, CharacterInfo] => [
          key,
          { name: c.name, color: c.color ?? undefined },
        ]),
      ),
    [game],
  );

  if (load.kind === "loading") return <div className="gu-fill gu-muted">Загружаем сцену…</div>;
  if (load.kind === "error")
    return (
      <div className="gu-fill">
        <p>Сцена не загрузилась.</p>
        <button type="button" onClick={() => setAttempt((n) => n + 1)}>
          Ещё раз
        </button>
      </div>
    );
  return (
    <VnScene
      runner={load.runner}
      assets={assets}
      characters={characters}
      playerName={playerName}
      onEnd={onEnd}
    />
  );
}
