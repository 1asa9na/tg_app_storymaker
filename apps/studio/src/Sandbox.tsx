import { GameScreen, type GameData, type View } from "@storymaker/game-ui";
import {
  GameError,
  type Action,
  type ActionResult,
  type GameClient,
  type SaveState,
} from "@storymaker/game-ui/types";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { problems, StudioError } from "./api";

// Песочница сборки: тот же экран игры, что в плеере, в рамке телефона, и панели отладки рядом.
// Сохранение — слот sandbox:<сборка> сотрудника; на телефоне по превью-ссылке оно то же самое.

interface LogEntry {
  at: string;
  revision: number;
  action: Record<string, unknown>;
  outcome: { changes: { path: string; delta: number }[]; new_day: boolean } | null;
  time: { day: number; slot: string } | null;
}

async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method,
    credentials: "same-origin",
    headers: method === "GET" ? {} : { "Content-Type": "application/json", "X-Studio": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 409) {
    const { detail } = (await response.json()) as { detail: { code: string; message: string } };
    throw new GameError(detail.code, detail.message ?? detail.code);
  }
  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail;
    } catch {
      // не JSON
    }
    throw new StudioError(response.status, detail);
  }
  return (await response.json()) as T;
}

function sandboxClient(base: string): GameClient {
  return {
    game: () => call<GameData>("GET", `${base}/game`),
    state: () => call<View>("GET", `${base}/state`),
    act: (action: Action, revision: number) =>
      call<ActionResult>("POST", `${base}/actions`, {
        request_id: crypto.randomUUID(),
        revision,
        action,
      }),
    scene: (key: string) => call<{ key: string; json: string }>("GET", `${base}/scenes/${key}`),
    restart: (revision: number) =>
      call<View>("POST", `${base}/restart`, { request_id: crypto.randomUUID(), revision }),
  };
}

export function Sandbox({
  slug,
  buildId,
  version,
  editor,
}: {
  slug: string;
  buildId: number;
  version: number | null;
  editor: boolean;
}) {
  const base = `/api/studio/titles/${slug}/builds/${buildId}/sandbox`;
  const client = useMemo(() => sandboxClient(base), [base]);
  const [game, setGame] = useState<GameData | null>(null);
  const [view, setView] = useState<View | null>(null);
  // Новый ключ перезапускает экран игры после правки состояния из отладки.
  const [screenKey, setScreenKey] = useState(0);
  const [logKey, setLogKey] = useState(0);

  useEffect(() => {
    client.game().then(setGame, () => setGame(null));
  }, [client]);

  const onChange = useCallback((next: View) => {
    setView(next);
    setLogKey((n) => n + 1);
  }, []);

  return (
    <div className="sandbox">
      <div className="phone">
        <GameScreen
          key={screenKey}
          client={client}
          badge={`Песочница${version ? ` v${version}` : ""}`}
          onChange={onChange}
          onExit={() => setScreenKey((n) => n + 1)}
        />
      </div>
      <div className="panels">
        <Preview slug={slug} buildId={buildId} />
        {game && view && (
          <Debug base={base} game={game} view={view} onApplied={() => setScreenKey((n) => n + 1)} />
        )}
        <Log base={base} reload={logKey} />
        {editor && game && <Simulator slug={slug} buildId={buildId} game={game} />}
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="card">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function Preview({ slug, buildId }: { slug: string; buildId: number }) {
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const send = async () => {
    setBusy(true);
    try {
      const response = await call<{ url: string; sent: boolean }>(
        "POST",
        `/api/studio/titles/${slug}/builds/${buildId}/preview`,
        {},
      );
      setResult(
        response.sent
          ? "Бот прислал вам кнопку «Открыть превью». Прогресс общий с этой песочницей."
          : `Бот не смог написать вам (нажмите /start в боте). Ссылка: ${response.url}`,
      );
    } catch (error) {
      setResult(problems(error)[0] ?? "Не получилось");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="На телефоне">
      <p className="muted">
        Та же песочница в Telegram: бот пришлёт кнопку, она откроет эту сборку в Mini App. Ссылка
        работает 7 дней и только у команды.
      </p>
      <button type="button" disabled={busy} onClick={send}>
        Прислать в Telegram
      </button>
      {result && <p className="muted small">{result}</p>}
    </Panel>
  );
}

type Draft = SaveState;

const PRESETS = (slug: string) => `storymaker.presets.${slug}`;

function loadPresets(slug: string): Record<string, Draft> {
  try {
    return JSON.parse(localStorage.getItem(PRESETS(slug)) ?? "{}") as Record<string, Draft>;
  } catch {
    return {};
  }
}

function Debug({
  base,
  game,
  view,
  onApplied,
}: {
  base: string;
  game: GameData;
  view: View;
  onApplied(): void;
}) {
  const [draft, setDraft] = useState<Draft>(() => structuredClone(view.state));
  const [dirty, setDirty] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [flag, setFlag] = useState("");
  const [presetName, setPresetName] = useState("");
  const [presets, setPresets] = useState(() => loadPresets(game.slug));

  // Пока черновик не трогали, он следует за игрой.
  const [seen, setSeen] = useState(view);
  if (seen !== view && !dirty) {
    setSeen(view);
    setDraft(structuredClone(view.state));
  }

  const edit = (patch: (d: Draft) => void) => {
    setDraft((current) => {
      const next = structuredClone(current);
      patch(next);
      return next;
    });
    setDirty(true);
  };

  const apply = async (state: Draft) => {
    setErrors([]);
    try {
      await call("PUT", `${base}/debug/state`, { state });
      setDirty(false);
      onApplied();
    } catch (error) {
      setErrors(problems(error));
    }
  };

  const savePreset = () => {
    if (!presetName) return;
    const next = { ...presets, [presetName]: draft };
    setPresets(next);
    try {
      localStorage.setItem(PRESETS(game.slug), JSON.stringify(next));
    } catch {
      // хранилище недоступно — пресет живёт до перезагрузки
    }
    setPresetName("");
  };

  const number = (value: number, onChange: (n: number) => void) => (
    <input type="number" value={value} onChange={(e) => onChange(Number(e.target.value) || 0)} />
  );

  return (
    <Panel title="Отладка">
      <div className="grid">
        <label>
          День
          {number(draft.day, (n) => edit((d) => (d.day = Math.max(1, n))))}
        </label>
        <label>
          Время
          <select
            value={draft.slot}
            onChange={(e) => edit((d) => (d.slot = Number(e.target.value)))}
          >
            {game.time.slots.map((slot, index) => (
              <option key={slot.id} value={index}>
                {slot.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Где
          <select
            value={draft.location ?? ""}
            onChange={(e) => edit((d) => (d.location = e.target.value || null))}
          >
            <option value="">на карте</option>
            {Object.entries(game.locations).map(([key, location]) => (
              <option key={key} value={key}>
                {location.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Уровень аккаунта
          {number(draft.global_level, (n) => edit((d) => (d.global_level = Math.max(1, n))))}
        </label>
        {Object.entries(game.resources).map(([key, resource]) => (
          <label key={key}>
            {resource.name}
            {number(draft.resources[key]?.value ?? 0, (n) =>
              edit((d) => {
                const target = d.resources[key];
                if (target) target.value = n;
              }),
            )}
          </label>
        ))}
        {Object.entries(game.stats).map(([key, stat]) => (
          <label key={key}>
            {stat.name}
            {number(draft.stats[key] ?? 0, (n) => edit((d) => (d.stats[key] = n)))}
          </label>
        ))}
        {Object.entries(game.characters).map(([key, character]) => (
          <label key={key}>
            {character.name} ♥
            {number(draft.affection[key] ?? 0, (n) => edit((d) => (d.affection[key] = n)))}
          </label>
        ))}
        {Object.entries(game.items).map(([key, item]) => (
          <label key={key}>
            {item.name}
            {number(draft.items[key] ?? 0, (n) =>
              edit((d) => {
                if (n > 0) d.items[key] = n;
                else delete d.items[key];
              }),
            )}
          </label>
        ))}
      </div>

      <h3>Квесты</h3>
      <div className="grid">
        {Object.entries(game.quests).map(([key, quest]) => {
          const progress = draft.quests[key];
          const value = !progress
            ? ""
            : progress.status === "done"
              ? "done"
              : String(progress.stage);
          return (
            <label key={key}>
              {quest.name}
              <select
                value={value}
                onChange={(e) =>
                  edit((d) => {
                    const v = e.target.value;
                    if (v === "") delete d.quests[key];
                    else if (v === "done")
                      d.quests[key] = { status: "done", stage: quest.stages.length - 1 };
                    else d.quests[key] = { status: "active", stage: Number(v) };
                  })
                }
              >
                <option value="">не начат</option>
                {quest.stages.map((stage, index) => (
                  <option key={stage.id} value={index}>
                    этап {index + 1}: {stage.journal}
                  </option>
                ))}
                <option value="done">выполнен</option>
              </select>
            </label>
          );
        })}
      </div>

      <h3>Флаги</h3>
      <div className="flags">
        {Object.entries(draft.flags).map(([key, value]) => (
          <label key={key} className="check">
            <input
              type="checkbox"
              checked={value}
              onChange={(e) => edit((d) => (d.flags[key] = e.target.checked))}
            />
            {key}
          </label>
        ))}
        <span className="add-flag">
          <input
            value={flag}
            placeholder="новый_флаг"
            onChange={(e) => setFlag(e.target.value.trim())}
          />
          <button
            type="button"
            className="small secondary"
            disabled={!/^[a-z][a-z0-9_]*$/.test(flag)}
            onClick={() => {
              edit((d) => (d.flags[flag] = true));
              setFlag("");
            }}
          >
            Добавить
          </button>
        </span>
      </div>

      {draft.pending_scenes.length > 0 && (
        <p className="muted small">
          В очереди сцены: {draft.pending_scenes.map((p) => p.scene).join(", ")}{" "}
          <button
            type="button"
            className="link"
            onClick={() => edit((d) => (d.pending_scenes = []))}
          >
            снять
          </button>
        </p>
      )}

      <div className="actions">
        <button type="button" disabled={!dirty} onClick={() => apply(draft)}>
          Применить
        </button>
        <button
          type="button"
          className="secondary"
          disabled={!dirty}
          onClick={() => {
            setDirty(false);
            setDraft(structuredClone(view.state));
          }}
        >
          Отменить правки
        </button>
      </div>
      <Problems items={errors} />

      <h3>Пресеты</h3>
      <div className="flags">
        {Object.keys(presets).map((name) => (
          <button
            key={name}
            type="button"
            className="small secondary"
            onClick={() => apply({ ...presets[name]!, title: game.slug })}
          >
            {name}
          </button>
        ))}
        <span className="add-flag">
          <input
            value={presetName}
            placeholder="день 5, Анна 25"
            onChange={(e) => setPresetName(e.target.value)}
          />
          <button
            type="button"
            className="small secondary"
            disabled={!presetName}
            onClick={savePreset}
          >
            Сохранить текущее
          </button>
        </span>
      </div>
      <p className="muted small">Пресеты хранятся в этом браузере.</p>
    </Panel>
  );
}

function Problems({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="problems error">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

function describeAction(action: Record<string, unknown>): string {
  const { type, ...rest } = action;
  const details = Object.entries(rest)
    .filter(([key]) => key !== "effects")
    .map(([, value]) => String(value))
    .join(" ");
  return `${String(type)}${details ? ` ${details}` : ""}`;
}

function Log({ base, reload }: { base: string; reload: number }) {
  const [entries, setEntries] = useState<LogEntry[]>([]);

  useEffect(() => {
    call<LogEntry[]>("GET", `${base}/debug/log`).then(setEntries, () => setEntries([]));
  }, [base, reload]);

  return (
    <Panel title="Лог действий">
      {entries.length === 0 ? (
        <p className="muted">Пока пусто.</p>
      ) : (
        <ol className="log">
          {entries.map((entry) => (
            <li key={entry.revision}>
              <span className="muted small">
                {entry.time ? `д${entry.time.day} ${entry.time.slot}` : ""}
              </span>{" "}
              <code>{describeAction(entry.action)}</code>
              {entry.outcome && entry.outcome.changes.length > 0 && (
                <span className="muted small">
                  {" "}
                  {entry.outcome.changes
                    .map((c) => `${c.path} ${c.delta > 0 ? "+" : ""}${c.delta}`)
                    .join(", ")}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}

function Simulator({ slug, buildId, game }: { slug: string; buildId: number; game: GameData }) {
  const [players, setPlayers] = useState(50);
  const [strategy, setStrategy] = useState("random");
  const metrics = useMemo(() => goalMetrics(game), [game]);
  const [metric, setMetric] = useState(() => metrics[0]?.path ?? "global.xp");
  const [direction, setDirection] = useState<"max" | "min">("max");
  const [scenes, setScenes] = useState("free");
  const [gap, setGap] = useState(4);
  const [result, setResult] = useState<{ report: string; seconds: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(
        await call("POST", `/api/studio/titles/${slug}/builds/${buildId}/simulate`, {
          players,
          strategy: strategy === "goal" ? `goal:${metric}:${direction}` : strategy,
          scene_strategy: scenes,
          session_gap_hours: gap,
        }),
      );
    } catch (e) {
      setError(problems(e)[0] ?? "Не получилось");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Симулятор баланса">
      <div className="grid">
        <label>
          Игроков
          <input
            type="number"
            min={1}
            max={300}
            value={players}
            onChange={(e) => setPlayers(Number(e.target.value) || 1)}
          />
        </label>
        <label>
          Стратегия
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
            <option value="random">случайные занятия</option>
            {Object.entries(game.characters).map(([key, c]) => (
              <option key={key} value={`romance:${key}`}>
                роман с {c.name}
              </option>
            ))}
            <option value="goal">цель: метрика…</option>
          </select>
        </label>
        {strategy === "goal" && (
          <>
            <label>
              Метрика
              <select value={metric} onChange={(e) => setMetric(e.target.value)}>
                {metrics.map((m) => (
                  <option key={m.path} value={m.path}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Направление
              <select
                value={direction}
                onChange={(e) => setDirection(e.target.value as "max" | "min")}
              >
                <option value="max">максимизировать</option>
                <option value="min">минимизировать</option>
              </select>
            </label>
          </>
        )}
        <label>
          Выборы в сценах
          <select value={scenes} onChange={(e) => setScenes(e.target.value)}>
            <option value="free">без платных</option>
            <option value="random">случайные</option>
            <option value="first">первый вариант</option>
          </select>
        </label>
        <label>
          Пауза между сессиями, ч
          <input
            type="number"
            min={1}
            value={gap}
            onChange={(e) => setGap(Number(e.target.value) || 1)}
          />
        </label>
      </div>
      <button type="button" disabled={busy} onClick={run}>
        {busy ? "Считаем…" : "Запустить"}
      </button>
      {error && <p className="error">{error}</p>}
      {result && (
        <>
          <p className="muted small">Посчитано за {result.seconds} с.</p>
          <Markdown text={result.report} />
        </>
      )}
    </Panel>
  );
}

/** Что может двигать стратегия-цель: характеристики, ресурсы, симпатия, предметы, опыт. */
function goalMetrics(game: GameData): { path: string; label: string }[] {
  return [
    ...Object.entries(game.stats).map(([k, v]) => ({ path: `stat.${k}`, label: v.name })),
    ...Object.entries(game.resources).map(([k, v]) => ({ path: `resource.${k}`, label: v.name })),
    ...Object.entries(game.characters).map(([k, v]) => ({
      path: `affection.${k}`,
      label: `симпатия: ${v.name}`,
    })),
    ...Object.entries(game.items).map(([k, v]) => ({
      path: `item.${k}`,
      label: `предмет: ${v.name}`,
    })),
    { path: "global.xp", label: "опыт аккаунта" },
  ];
}

/** Отчёт симулятора: заголовки, абзацы и таблицы — больше Markdown там нет. */
function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    if (line.startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i]!.startsWith("|")) {
        const cells = lines[i]!.split("|")
          .slice(1, -1)
          .map((c) => c.trim());
        if (!cells.every((c) => /^-+$/.test(c))) rows.push(cells);
        i++;
      }
      i--;
      const [head, ...body] = rows;
      blocks.push(
        <table key={i}>
          <thead>
            <tr>
              {head?.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((row, r) => (
              <tr key={r}>
                {row.map((c, k) => (
                  <td key={k}>{c}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>,
      );
    } else if (line.startsWith("## ")) {
      blocks.push(<h3 key={i}>{line.slice(3)}</h3>);
    } else if (line.startsWith("# ")) {
      blocks.push(<h3 key={i}>{line.slice(2)}</h3>);
    } else if (line.trim()) {
      blocks.push(<p key={i}>{line}</p>);
    }
  }
  return <div className="report">{blocks}</div>;
}
