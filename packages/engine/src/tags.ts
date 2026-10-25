// Грамматика тегов сцены: `# bg: gym`, `# show: anna smirk left`, `# effect: affection anna +3`.
// Спецификация — docs/SCENE_FORMAT.md.

export type Position = "left" | "center" | "right";

export type Command =
  | { type: "bg"; key: string }
  | { type: "show"; character: string; emotion: string; position: Position | null }
  | { type: "hide"; character: string }
  | { type: "music"; key: string | null }
  | { type: "sfx"; key: string }
  | { type: "wait"; seconds: number }
  | { type: "fx"; name: "shake" | "flash" };

export type Effect =
  | { op: "affection"; character: string; delta: number }
  | { op: "stat"; stat: string; delta: number }
  | { op: "give"; item: string; count: number }
  | { op: "take"; item: string; count: number }
  | { op: "flag"; flag: string; value: boolean }
  | { op: "start_quest"; quest: string }
  | { op: "advance_quest"; quest: string }
  | { op: "xp"; amount: number }
  | { op: "achievement"; key: string };

export type Tag =
  | { kind: "command"; command: Command }
  | { kind: "effect"; effect: Effect }
  | { kind: "premium"; price: number };

export class TagError extends Error {}

const KEY = /^[a-z][a-z0-9_]*$/;
const DELTA = /^[+-]\d+$/;
const POSITIVE = /^[1-9]\d*$/;
const POSITIONS: readonly Position[] = ["left", "center", "right"];

function key(value: string | undefined, what: string): string {
  if (value === undefined || !KEY.test(value)) {
    throw new TagError(
      `${what}: ожидается ключ латиницей в нижнем регистре, получено «${value ?? ""}»`,
    );
  }
  return value;
}

function delta(value: string | undefined): number {
  if (value === undefined || !DELTA.test(value)) {
    throw new TagError(
      `ожидается изменение со знаком, например +3 или -1, получено «${value ?? ""}»`,
    );
  }
  return Number(value);
}

function count(value: string | undefined): number {
  if (value === undefined) {
    return 1;
  }
  if (!POSITIVE.test(value)) {
    throw new TagError(`ожидается положительное число, получено «${value}»`);
  }
  return Number(value);
}

function arity(args: string[], min: number, max: number, usage: string): void {
  if (args.length < min || args.length > max) {
    throw new TagError(`формат: ${usage}`);
  }
}

export function parseEffect(text: string): Effect {
  const [op, ...args] = text.trim().split(/\s+/);
  switch (op) {
    case "affection":
      arity(args, 2, 2, "affection <персонаж> <+n|-n>");
      return { op, character: key(args[0], "персонаж"), delta: delta(args[1]) };
    case "stat":
      arity(args, 2, 2, "stat <характеристика> <+n|-n>");
      return { op, stat: key(args[0], "характеристика"), delta: delta(args[1]) };
    case "give":
    case "take":
      arity(args, 1, 2, `${op} <предмет> [количество]`);
      return { op, item: key(args[0], "предмет"), count: count(args[1]) };
    case "flag":
    case "unflag":
      arity(args, 1, 1, `${op} <флаг>`);
      return { op: "flag", flag: key(args[0], "флаг"), value: op === "flag" };
    case "start_quest":
    case "advance_quest":
      arity(args, 1, 1, `${op} <квест>`);
      return { op, quest: key(args[0], "квест") };
    case "xp":
      arity(args, 1, 1, "xp <количество>");
      return { op, amount: count(args[0]) };
    case "achievement":
      arity(args, 1, 1, "achievement <ключ>");
      return { op, key: key(args[0], "достижение") };
    default:
      throw new TagError(`неизвестный эффект «${op ?? ""}»`);
  }
}

export function parseTag(raw: string): Tag {
  const separator = raw.indexOf(":");
  if (separator === -1) {
    throw new TagError(`тег без двоеточия: «${raw}»`);
  }
  const name = raw.slice(0, separator).trim();
  const rest = raw.slice(separator + 1).trim();
  const args = rest ? rest.split(/\s+/) : [];

  switch (name) {
    case "bg":
      arity(args, 1, 1, "bg: <фон>");
      return { kind: "command", command: { type: "bg", key: key(args[0], "фон") } };
    case "show": {
      arity(args, 2, 3, "show: <персонаж> <эмоция> [left|center|right]");
      const position = args[2] ?? null;
      if (position !== null && !POSITIONS.includes(position as Position)) {
        throw new TagError(`позиция: left, center или right, получено «${position}»`);
      }
      return {
        kind: "command",
        command: {
          type: "show",
          character: key(args[0], "персонаж"),
          emotion: key(args[1], "эмоция"),
          position: position as Position | null,
        },
      };
    }
    case "hide":
      arity(args, 1, 1, "hide: <персонаж>");
      return { kind: "command", command: { type: "hide", character: key(args[0], "персонаж") } };
    case "music":
      arity(args, 1, 1, "music: <трек>|stop");
      return {
        kind: "command",
        command: { type: "music", key: args[0] === "stop" ? null : key(args[0], "трек") },
      };
    case "sfx":
      arity(args, 1, 1, "sfx: <звук>");
      return { kind: "command", command: { type: "sfx", key: key(args[0], "звук") } };
    case "wait": {
      arity(args, 1, 1, "wait: <секунды>");
      const seconds = Number(args[0]);
      if (!Number.isFinite(seconds) || seconds <= 0 || seconds > 10) {
        throw new TagError(`wait: от 0 до 10 секунд, получено «${args[0]}»`);
      }
      return { kind: "command", command: { type: "wait", seconds } };
    }
    case "fx":
      arity(args, 1, 1, "fx: shake|flash");
      if (args[0] !== "shake" && args[0] !== "flash") {
        throw new TagError(`fx: shake или flash, получено «${args[0]}»`);
      }
      return { kind: "command", command: { type: "fx", name: args[0] } };
    case "effect":
      return { kind: "effect", effect: parseEffect(rest) };
    case "premium":
      arity(args, 1, 1, "premium: <цена>");
      return { kind: "premium", price: count(args[0]) };
    default:
      throw new TagError(`неизвестный тег «${name}»`);
  }
}
