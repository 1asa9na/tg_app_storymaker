import { SceneRunner, type Effect, type GameSnapshot } from "@storymaker/engine";
import { withPlaceholders } from "@storymaker/game-ui/placeholders";
import type { AssetManifest } from "@storymaker/game-ui/types";
import { VnScene, type CharacterInfo } from "@storymaker/vn-renderer";
import { useMemo, useState } from "react";

import type { Node, SceneContext } from "./analysis";

// Превью сцены в рамке телефона: последняя удачно скомпилированная версия текста,
// стартовое состояние игры задаётся здесь же и запоминается в браузере.

interface Props {
  slug: string;
  context: SceneContext;
  /** JSON последней удачной компиляции; null — сцена ещё ни разу не скомпилировалась. */
  json: string | null;
  /** Сцену уже проверили хотя бы раз: без JSON это значит, что в ней ошибки. */
  checked: boolean;
  nodes: Node[];
  /** Узел под курсором редактора. */
  cursor: Node | null;
  /** Флаги из текста сцены, которых ещё нет в сохранённых данных. */
  sceneFlags: string[];
}

interface StartState {
  affection: Record<string, number>;
  stats: Record<string, number>;
  items: Record<string, number>;
  flags: Record<string, boolean>;
  globalLevel: number;
}

const EMPTY: StartState = { affection: {}, stats: {}, items: {}, flags: {}, globalLevel: 1 };
const CURSOR = "@cursor";

type Run =
  | { kind: "idle" }
  | { kind: "error"; message: string }
  | { kind: "playing"; runner: SceneRunner; id: number; json: string }
  | { kind: "ended"; effects: Effect[]; json: string };

function load(slug: string): StartState {
  try {
    const saved = localStorage.getItem(`storymaker:scene-start:${slug}`);
    return saved ? { ...EMPTY, ...(JSON.parse(saved) as Partial<StartState>) } : EMPTY;
  } catch {
    return EMPTY;
  }
}

function store(slug: string, state: StartState) {
  try {
    localStorage.setItem(`storymaker:scene-start:${slug}`, JSON.stringify(state));
  } catch {
    // без хранилища состояние живёт до перезагрузки
  }
}

const sign = (n: number) => (n > 0 ? `+${n}` : String(n));

function describe(effect: Effect, context: SceneContext): string {
  const name = (names: Record<string, string>, key: string) => names[key] ?? key;
  switch (effect.op) {
    case "affection":
      return `Симпатия: ${context.characters[effect.character]?.name ?? effect.character} ${sign(effect.delta)}`;
    case "stat":
      return `${name(context.stats, effect.stat)} ${sign(effect.delta)}`;
    case "give":
      return `Получен предмет: ${name(context.items, effect.item)} ×${effect.count}`;
    case "take":
      return `Забран предмет: ${name(context.items, effect.item)} ×${effect.count}`;
    case "flag":
      return `Флаг ${effect.flag}: ${effect.value ? "поставлен" : "снят"}`;
    case "start_quest":
      return `Начат квест «${name(context.quests, effect.quest)}»`;
    case "advance_quest":
      return `Этап квеста «${name(context.quests, effect.quest)}» пройден`;
    case "xp":
      return `Опыт аккаунта +${effect.amount}`;
    case "achievement":
      return `Достижение «${name(context.achievements, effect.key)}»`;
  }
}

export function Preview({ slug, context, json, checked, nodes, cursor, sceneFlags }: Props) {
  const [start, setStart] = useState<StartState>(() => load(slug));
  const [from, setFrom] = useState("");
  const [run, setRun] = useState<Run>({ kind: "idle" });

  const update = (next: StartState) => {
    setStart(next);
    store(slug, next);
  };

  const assets = useMemo(
    () =>
      withPlaceholders({
        assets: context.manifest as AssetManifest,
        locations: Object.fromEntries(
          Object.entries(context.locations).flatMap(([key, l]) =>
            l.background ? [[key, { name: l.name, background: l.background }]] : [],
          ),
        ),
        characters: context.characters,
      }),
    [context],
  );
  const characters = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(context.characters).map(([key, c]): [string, CharacterInfo] => [
          key,
          { name: c.name, color: c.color ?? undefined },
        ]),
      ),
    [context],
  );
  const flags = useMemo(
    () => [...new Set([...context.flags, ...sceneFlags])].sort(),
    [context.flags, sceneFlags],
  );
  const targets = nodes.filter((node) => node.kind === "knot" || node.kind === "stitch");

  const play = () => {
    if (!json) return;
    const snapshot: GameSnapshot = {
      affection: start.affection,
      stats: start.stats,
      items: start.items,
      flags: start.flags,
      globalLevel: start.globalLevel,
    };
    const path = from === CURSOR ? (cursor?.path ?? "") : from;
    try {
      const runner = new SceneRunner(json, snapshot);
      if (path) runner.startAt(path);
      setRun({ kind: "playing", runner, id: Date.now(), json });
    } catch (error) {
      setRun({ kind: "error", message: (error as Error).message });
    }
  };

  const stale = (run.kind === "playing" || run.kind === "ended") && run.json !== json;

  return (
    <div className="scene-preview">
      <div className="preview-bar">
        <select value={from} onChange={(e) => setFrom(e.target.value)} aria-label="Откуда играть">
          <option value="">С начала сцены</option>
          <option value={CURSOR}>
            С узла под курсором{cursor ? `: ${cursor.path}` : " (курсор вне узлов)"}
          </option>
          {targets.map((node) => (
            <option key={node.path} value={node.path}>
              {node.path}
            </option>
          ))}
        </select>
        <button type="button" disabled={!json} onClick={play}>
          {run.kind === "idle" ? "▶ Играть" : "↻ Заново"}
        </button>
      </div>
      {stale && <p className="muted small">Текст изменился — нажмите «Заново», чтобы увидеть.</p>}

      <div className="phone phone-small">
        {run.kind === "playing" ? (
          <VnScene
            key={run.id}
            runner={run.runner}
            assets={assets}
            characters={characters}
            typingDelay={15}
            onEnd={(effects) => setRun({ kind: "ended", effects, json: run.json })}
          />
        ) : (
          <div className="phone-message">
            {run.kind === "error" ? (
              <p className="error">Не удалось запустить: {run.message}</p>
            ) : run.kind === "ended" ? (
              <>
                <p>Сцена закончилась.</p>
                {run.effects.length ? (
                  <ul>
                    {run.effects.map((effect, i) => (
                      <li key={i}>{describe(effect, context)}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">Эффектов нет.</p>
                )}
              </>
            ) : json ? (
              <p className="muted">Нажмите «Играть»</p>
            ) : !checked ? (
              <p className="muted">Проверяем сцену…</p>
            ) : (
              <p className="muted">Исправьте ошибки — превью появится после удачной компиляции.</p>
            )}
          </div>
        )}
      </div>

      <details className="card start-state">
        <summary>Состояние на старте</summary>
        <p className="muted small">
          Что сцена видит через affection(), has(), flag(), stat() и global_level().
        </p>
        <Numbers
          title="Симпатия"
          names={Object.fromEntries(
            Object.entries(context.characters).map(([key, c]) => [key, c.name]),
          )}
          values={start.affection}
          onChange={(affection) => update({ ...start, affection })}
        />
        <Numbers
          title="Характеристики"
          names={context.stats}
          values={start.stats}
          onChange={(stats) => update({ ...start, stats })}
        />
        <Numbers
          title="Предметы"
          names={context.items}
          values={start.items}
          onChange={(items) => update({ ...start, items })}
        />
        {flags.length > 0 && (
          <fieldset className="plain">
            <legend>Флаги</legend>
            <div className="flags">
              {flags.map((flag) => (
                <label key={flag} className="check">
                  <input
                    type="checkbox"
                    checked={start.flags[flag] ?? false}
                    onChange={(e) =>
                      update({ ...start, flags: { ...start.flags, [flag]: e.target.checked } })
                    }
                  />
                  {flag}
                </label>
              ))}
            </div>
          </fieldset>
        )}
        <label>
          Уровень аккаунта
          <input
            type="number"
            min={1}
            value={start.globalLevel}
            onChange={(e) => update({ ...start, globalLevel: Number(e.target.value) || 1 })}
          />
        </label>
        <button type="button" className="secondary small" onClick={() => update(EMPTY)}>
          Сбросить
        </button>
      </details>
    </div>
  );
}

function Numbers({
  title,
  names,
  values,
  onChange,
}: {
  title: string;
  names: Record<string, string>;
  values: Record<string, number>;
  onChange(next: Record<string, number>): void;
}) {
  const entries = Object.entries(names);
  if (!entries.length) return null;
  return (
    <fieldset className="plain">
      <legend>{title}</legend>
      <div className="grid">
        {entries.map(([key, name]) => (
          <label key={key}>
            {name}
            <input
              type="number"
              value={values[key] ?? 0}
              onChange={(e) => onChange({ ...values, [key]: Number(e.target.value) || 0 })}
            />
          </label>
        ))}
      </div>
    </fieldset>
  );
}
