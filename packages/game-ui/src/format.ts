import type { Change, GameData, Outcome, SaveState } from "./types.ts";

const sign = (n: number) => (n > 0 ? `+${n}` : `−${-n}`);

/** Название пути состояния для игрока: stat.fitness → «Форма». */
export function pathName(path: string, game: GameData): string {
  const [head, key = ""] = path.split(".", 2);
  switch (head) {
    case "stat":
      return game.stats[key]?.name ?? key;
    case "resource":
      return game.resources[key]?.name ?? key;
    case "affection":
      return `${game.characters[key]?.name ?? key} ♥`;
    case "item":
      return game.items[key]?.name ?? key;
    case "global":
      return "Опыт";
    default:
      return path;
  }
}

/** «Форма +3», «Энергия −20». */
export function formatChange(change: Change, game: GameData): string {
  return `${pathName(change.path, game)} ${sign(change.delta)}`;
}

/** Цена и эффекты занятия в одну строку для кнопки. */
export function formatCost(cost: Record<string, number>, game: GameData): string[] {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(cost)) {
    if (key === "slots") {
      if (value > 0) parts.push(value === 1 ? "часть дня" : `${value} части дня`);
    } else if (value > 0) {
      parts.push(`${game.resources[key]?.name ?? key} ${sign(-value)}`);
    }
  }
  return parts;
}

export function formatEffects(effects: Record<string, number>, game: GameData): string[] {
  return Object.entries(effects).map(([path, delta]) => formatChange({ path, delta }, game));
}

/** Строки сводки после действия: изменения, опыт, квесты, достижения. */
export function describeOutcome(outcome: Outcome, game: GameData): string[] {
  const lines = outcome.changes.map((change) => formatChange(change, game));
  if (outcome.xp > 0) lines.push(`Опыт ${sign(outcome.xp)}`);
  for (const quest of outcome.quests) {
    const name = game.quests[quest.quest]?.name ?? quest.quest;
    if (quest.status === "done") lines.push(`Квест выполнен: ${name}`);
    else if (quest.stage === null || quest.stage === game.quests[quest.quest]?.stages[0]?.id)
      lines.push(`Новый квест: ${name}`);
    else lines.push(`Квест обновлён: ${name}`);
  }
  for (const key of outcome.achievements) {
    lines.push(`Достижение: ${game.achievements[key]?.name ?? key}`);
  }
  return lines;
}

/** Суммирует изменения за день по путям, нулевые выбрасывает. */
export function sumChanges(changes: Change[]): Change[] {
  const total = new Map<string, number>();
  for (const { path, delta } of changes) total.set(path, (total.get(path) ?? 0) + delta);
  return [...total].filter(([, delta]) => delta !== 0).map(([path, delta]) => ({ path, delta }));
}

/** Название уровня отношений по симпатии. */
export function relationLevel(levels: { at: number; name: string }[], value: number): string {
  let name = "";
  for (const level of levels) if (value >= level.at) name = level.name;
  return name;
}

/** Текст журнала: текущий этап активного квеста. */
export function questJournal(state: SaveState, game: GameData, quest: string): string | null {
  const progress = state.quests[quest];
  if (!progress || progress.status !== "active") return null;
  return game.quests[quest]?.stages[progress.stage]?.journal ?? null;
}

/** «через 4:59» до следующей единицы ресурса. */
export function countdown(nextAt: string, now: number): string {
  const seconds = Math.max(0, Math.ceil((Date.parse(nextAt) - now) / 1000));
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}
