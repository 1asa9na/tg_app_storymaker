import type { Effect } from "@storymaker/engine";
import type { AssetResolver } from "@storymaker/vn-renderer";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DaySummary, Sheet, TabBar, Toasts, TopBar, type Tab, type Toast } from "./chrome.tsx";
import { describeOutcome, formatCost, formatEffects, sumChanges } from "./format.ts";
import { BagPanel, JournalPanel, MapPanel, PeoplePanel, PlacePanel } from "./panels.tsx";
import { withPlaceholders } from "./placeholders.ts";
import { SceneLayer } from "./SceneLayer.tsx";
import {
  GameError,
  type Action,
  type Activity,
  type Change,
  type GameClient,
  type GameData,
  type Haptic,
  type View,
} from "./types.ts";
import "./game-ui.css";

export interface GameScreenProps {
  client: GameClient;
  /** Настоящие ассеты тайтла; чего нет — рисуется заглушкой. */
  assets?: Partial<AssetResolver>;
  playerName?: string;
  haptic?(kind: Haptic): void;
  /**
   * Обработчик «назад» для системной кнопки: закрывает лист, уходит на карту, выходит.
   * Экран передаёт его при каждом изменении.
   */
  onBackHandler?(handler: () => void): void;
  onExit(): void;
}

type Sheet =
  | { kind: "activity"; activity: Activity }
  | { kind: "item"; item: string }
  | { kind: "summary"; day: number; changes: Change[] };

const TOAST_MS = 3500;

export function GameScreen({
  client,
  assets,
  playerName,
  haptic,
  onBackHandler,
  onExit,
}: GameScreenProps) {
  const [game, setGame] = useState<GameData | null>(null);
  const [view, setView] = useState<View | null>(null);
  const [failed, setFailed] = useState(false);
  const [tab, setTab] = useState<Tab>("map");
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [busy, setBusy] = useState(false);
  // Изменения за текущий игровой день — для сводки, когда он закончится.
  const dayLog = useRef<Change[]>([]);
  const toastId = useRef(0);

  const toast = useCallback((lines: string[], kind: Toast["kind"] = "info") => {
    if (!lines.length) return;
    const id = ++toastId.current;
    setToasts((all) => [...all.slice(-2), { id, lines, kind }]);
    setTimeout(() => setToasts((all) => all.filter((t) => t.id !== id)), TOAST_MS);
  }, []);

  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    Promise.all([client.game(), client.state()]).then(
      ([data, state]) => {
        if (cancelled) return;
        setGame(data);
        setView(state);
        setTab(state.here.location ? "place" : "map");
      },
      () => !cancelled && setFailed(true),
    );
    return () => {
      cancelled = true;
    };
  }, [client, attempt]);

  const retry = () => {
    setFailed(false);
    setAttempt((n) => n + 1);
  };

  const refresh = useCallback(() => {
    client.state().then(setView, () => undefined);
  }, [client]);

  const resolver = useMemo(() => (game ? withPlaceholders(game, assets) : null), [game, assets]);

  const act = useCallback(
    async (action: Action) => {
      if (!view || !game || busy) return;
      setBusy(true);
      setSheet(null);
      try {
        const result = await client.act(action, view.revision);
        setView(result);
        haptic?.("success");
        const { outcome } = result;
        if (outcome.new_day) {
          const changes = sumChanges([...dayLog.current, ...outcome.changes]);
          dayLog.current = [];
          setSheet({ kind: "summary", day: view.time.day, changes });
        } else {
          dayLog.current.push(...outcome.changes);
          toast(describeOutcome(outcome, game));
        }
        if (outcome.new_day && outcome.achievements.length + outcome.quests.length > 0) {
          toast(describeOutcome({ ...outcome, changes: [] }, game));
        }
        if (result.account.level_up) toast([`Новый уровень аккаунта: ${result.account.level}`]);
        if (action.type === "go") setTab("place");
        if (action.type === "leave" || action.type === "sleep" || outcome.new_day) setTab("map");
      } catch (error) {
        haptic?.("error");
        if (error instanceof GameError) {
          toast([error.message], "error");
          if (error.code === "stale") refresh();
        } else {
          toast(["Нет связи с сервером. Попробуйте ещё раз."], "error");
        }
      } finally {
        setBusy(false);
      }
    },
    [busy, client, game, haptic, refresh, toast, view],
  );

  const back = useCallback(() => {
    if (sheet) setSheet(null);
    else if (tab !== "map" && tab !== "place") setTab(view?.here.location ? "place" : "map");
    else if (tab === "place") void act({ type: "leave" });
    else onExit();
  }, [act, onExit, sheet, tab, view]);

  useEffect(() => onBackHandler?.(back), [back, onBackHandler]);

  if (failed)
    return (
      <div className="gu-fill">
        <p>Не удалось загрузить игру.</p>
        <button type="button" onClick={retry}>
          Ещё раз
        </button>
        <button type="button" className="secondary" onClick={onExit}>
          Назад
        </button>
      </div>
    );
  if (!game || !view || !resolver) return <div className="gu-fill gu-muted">Загружаем…</div>;

  if (view.pending_scene) {
    return (
      <SceneLayer
        key={`${view.pending_scene}:${view.revision}`}
        client={client}
        game={game}
        scene={view.pending_scene}
        state={view.state}
        assets={resolver}
        playerName={playerName}
        onEnd={(effects: Effect[]) =>
          void act({ type: "scene_complete", scene: view.pending_scene!, effects })
        }
      />
    );
  }

  if (view.state.finished) {
    return (
      <div className="gu-fill">
        <h2>{game.name}</h2>
        <p>История пройдена. Спасибо, что играли!</p>
        <button
          type="button"
          onClick={() =>
            client.restart(view.revision).then(
              (fresh) => {
                dayLog.current = [];
                setView(fresh);
                setTab(fresh.here.location ? "place" : "map");
              },
              () => toast(["Не получилось начать заново"], "error"),
            )
          }
        >
          Начать заново
        </button>
        <button type="button" className="secondary" onClick={onExit}>
          К историям
        </button>
      </div>
    );
  }

  const here = view.here.location;
  const current = tab === "place" && !here ? "map" : tab;

  return (
    <div className={busy ? "gu-game gu-busy" : "gu-game"}>
      <TopBar game={game} view={view} onRegen={refresh} />
      <main className="gu-body">
        {current === "place" && (
          <PlacePanel
            game={game}
            view={view}
            assets={resolver}
            onActivity={(activity) => {
              haptic?.("tap");
              if (activity.lock) toast([activity.lock], "error");
              else setSheet({ kind: "activity", activity });
            }}
            onSleep={() => void act({ type: "sleep" })}
            onLeave={() => void act({ type: "leave" })}
          />
        )}
        {current === "map" && (
          <MapPanel
            game={game}
            view={view}
            assets={resolver}
            onGo={(location) => {
              haptic?.("tap");
              const target = view.locations.find((l) => l.id === location);
              if (target?.lock) toast([target.lock], "error");
              else if (location === here) setTab("place");
              else void act({ type: "go", location });
            }}
          />
        )}
        {current === "bag" && (
          <BagPanel
            game={game}
            view={view}
            assets={resolver}
            onItem={(item) => setSheet({ kind: "item", item })}
          />
        )}
        {current === "journal" && <JournalPanel game={game} view={view} />}
        {current === "people" && <PeoplePanel game={game} view={view} />}
      </main>
      <TabBar tab={current} hasPlace={Boolean(here)} onChange={setTab} />
      <Toasts
        toasts={toasts}
        onDismiss={(id) => setToasts((all) => all.filter((t) => t.id !== id))}
      />

      {sheet?.kind === "activity" && (
        <Sheet onClose={() => setSheet(null)}>
          <h2>{sheet.activity.name}</h2>
          {sheet.activity.description && <p>{sheet.activity.description}</p>}
          <ul className="gu-list">
            {formatCost(sheet.activity.cost, game).map((line) => (
              <li key={line} className="gu-down">
                {line}
              </li>
            ))}
            {formatEffects(sheet.activity.effects, game).map((line) => (
              <li key={line} className="gu-up">
                {line}
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => void act({ type: "activity", id: sheet.activity.id })}
          >
            Сделать
          </button>
        </Sheet>
      )}

      {sheet?.kind === "item" && (
        <ItemSheet
          game={game}
          view={view}
          item={sheet.item}
          onAct={(action) => void act(action)}
          onClose={() => setSheet(null)}
        />
      )}

      {sheet?.kind === "summary" && (
        <DaySummary
          game={game}
          day={sheet.day}
          changes={sheet.changes}
          onClose={() => setSheet(null)}
        />
      )}
    </div>
  );
}

function ItemSheet({
  game,
  view,
  item,
  onAct,
  onClose,
}: {
  game: GameData;
  view: View;
  item: string;
  onAct(action: Action): void;
  onClose(): void;
}) {
  const definition = game.items[item];
  const nearby = view.here.characters;
  return (
    <Sheet onClose={onClose}>
      <h2>{definition?.name ?? item}</h2>
      {definition?.description && <p>{definition.description}</p>}
      {definition?.kind === "consumable" && (
        <button type="button" onClick={() => onAct({ type: "use", item })}>
          Использовать
        </button>
      )}
      {definition?.kind === "gift" &&
        (nearby.length ? (
          nearby.map((character) => {
            const given = view.state.gifts_today[character] ?? 0;
            const name = game.characters[character]?.name ?? character;
            return (
              <button
                key={character}
                type="button"
                disabled={given >= game.gifts_per_day}
                onClick={() => onAct({ type: "gift", item, character })}
              >
                {given >= game.gifts_per_day ? `${name}: на сегодня хватит` : `Подарить: ${name}`}
              </button>
            );
          })
        ) : (
          <p className="gu-muted">Рядом никого — подарить некому.</p>
        ))}
    </Sheet>
  );
}
