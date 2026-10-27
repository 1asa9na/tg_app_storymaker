import { useEffect, useState, type ReactNode } from "react";

import { countdown, formatChange } from "./format.ts";
import type { Change, GameData, View } from "./types.ts";

export type Tab = "place" | "map" | "bag" | "journal" | "people";

/** День, время суток, ресурсы с таймером восстановления. */
export function TopBar({
  game,
  view,
  badge,
  onRegen,
}: {
  game: GameData;
  view: View;
  badge?: string;
  onRegen(): void;
}) {
  const [now, setNow] = useState(() => Date.now());
  const timers = Object.values(view.resources).some((r) => r.next_at);

  useEffect(() => {
    if (!timers) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [timers]);

  // Единица ресурса восстановилась: значение досчитает сервер.
  const due = Object.values(view.resources).some((r) => r.next_at && Date.parse(r.next_at) <= now);
  useEffect(() => {
    if (due) onRegen();
  }, [due, onRegen]);

  const slot = game.time.slots.find((s) => s.id === view.time.slot)?.name ?? view.time.slot;
  return (
    <header className="gu-topbar">
      <div className="gu-time">
        <strong>
          День {view.time.day}
          {game.time.days ? ` из ${game.time.days}` : ""}
        </strong>
        <span>
          {view.time.weekday ? `${view.time.weekday}, ` : ""}
          {slot.toLowerCase()}
        </span>
        {badge && <em className="gu-badge">{badge}</em>}
      </div>
      <div className="gu-resources">
        {Object.entries(view.resources).map(([key, r]) => (
          <div key={key} className="gu-resource">
            <span className="gu-resource-name">{game.resources[key]?.name ?? key}</span>
            <strong>
              {r.value}
              {r.max !== null ? `/${r.max}` : ""}
            </strong>
            {r.next_at && <small>+1 через {countdown(r.next_at, now)}</small>}
          </div>
        ))}
      </div>
    </header>
  );
}

const TABS: { id: Tab; label: string }[] = [
  { id: "place", label: "Здесь" },
  { id: "map", label: "Карта" },
  { id: "bag", label: "Сумка" },
  { id: "journal", label: "Журнал" },
  { id: "people", label: "Люди" },
];

export function TabBar({
  tab,
  hasPlace,
  onChange,
}: {
  tab: Tab;
  hasPlace: boolean;
  onChange(tab: Tab): void;
}) {
  return (
    <nav className="gu-tabs">
      {TABS.filter((t) => t.id !== "place" || hasPlace).map((t) => (
        <button
          key={t.id}
          type="button"
          className={t.id === tab ? "gu-tab gu-tab-active" : "gu-tab"}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </nav>
  );
}

/** Нижний лист с подтверждением: что это, сколько стоит, кнопки. */
export function Sheet({ children, onClose }: { children: ReactNode; onClose(): void }) {
  return (
    <div className="gu-sheet-backdrop" onClick={onClose}>
      <section className="gu-sheet" onClick={(event) => event.stopPropagation()}>
        {children}
      </section>
    </div>
  );
}

export interface Toast {
  id: number;
  lines: string[];
  kind: "info" | "error";
}

export function Toasts({ toasts, onDismiss }: { toasts: Toast[]; onDismiss(id: number): void }) {
  return (
    <div className="gu-toasts" aria-live="polite">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`gu-toast gu-toast-${toast.kind}`}
          onClick={() => onDismiss(toast.id)}
        >
          {toast.lines.map((line) => (
            <div key={line}>{line}</div>
          ))}
        </div>
      ))}
    </div>
  );
}

/** Итоги прошедшего дня. */
export function DaySummary({
  game,
  day,
  changes,
  onClose,
}: {
  game: GameData;
  day: number;
  changes: Change[];
  onClose(): void;
}) {
  return (
    <Sheet onClose={onClose}>
      <h2>День {day} позади</h2>
      {changes.length ? (
        <ul className="gu-list">
          {changes.map((change) => (
            <li key={change.path} className={change.delta > 0 ? "gu-up" : "gu-down"}>
              {formatChange(change, game)}
            </li>
          ))}
        </ul>
      ) : (
        <p className="gu-muted">Тихий день: ничего не изменилось.</p>
      )}
      <button type="button" onClick={onClose}>
        Новый день
      </button>
    </Sheet>
  );
}
