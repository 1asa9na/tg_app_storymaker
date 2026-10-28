// Разбор сцены для редактора без Monaco: узлы для переходов и превью, контекст подсказки
// по тексту строки до курсора. Грамматика тегов — packages/engine/src/tags.ts.

export interface SceneContext {
  scenes: { key: string; updated_at: string }[];
  /** Реестр для компилятора — тот же, что получает сборка. */
  registry: Record<string, unknown>;
  characters: Record<string, { name: string; color: string | null; emotions: string[] }>;
  items: Record<string, string>;
  stats: Record<string, string>;
  quests: Record<string, string>;
  achievements: Record<string, string>;
  flags: string[];
  backgrounds: string[];
  music: string[];
  sfx: string[];
  locations: Record<string, { name: string; background: string | null }>;
  manifest: Record<string, unknown>;
}

export interface Node {
  /** Путь для `->` и для запуска превью: `knot` или `knot.stitch`. */
  path: string;
  kind: "knot" | "stitch" | "label" | "function";
  /** Строка с 1. */
  line: number;
}

const KNOT = /^\s*={2,}\s*(function\s+)?([A-Za-z_]\w*)/;
const STITCH = /^\s*=\s*([A-Za-z_]\w*)/;
const LABEL = /^\s*(?:[-*+]\s*)+\(([A-Za-z_]\w*)\)/;

/** Узлы сцены по порядку: узлы `===`, подузлы `=` и метки выборов `(метка)`. */
export function outline(source: string): Node[] {
  const nodes: Node[] = [];
  let knot: string | null = null;
  let stitch: string | null = null;
  source.split("\n").forEach((text, index) => {
    const line = index + 1;
    const k = KNOT.exec(text);
    if (k) {
      knot = k[2]!;
      stitch = null;
      nodes.push({ path: knot, kind: k[1] ? "function" : "knot", line });
      return;
    }
    const s = STITCH.exec(text);
    if (s) {
      stitch = s[1]!;
      nodes.push({ path: knot ? `${knot}.${stitch}` : stitch, kind: "stitch", line });
      return;
    }
    const l = LABEL.exec(text);
    if (l) {
      const parent = [knot, stitch].filter(Boolean).join(".");
      nodes.push({ path: parent ? `${parent}.${l[1]}` : l[1]!, kind: "label", line });
    }
  });
  return nodes;
}

/** Узел, внутри которого стоит строка: для «запустить с курсора». */
export function nodeAt(nodes: Node[], line: number): Node | null {
  let found: Node | null = null;
  for (const node of nodes) {
    if (node.line > line) break;
    if (node.kind === "knot" || node.kind === "stitch") found = node;
    if (node.kind === "function") found = null;
  }
  return found;
}

export const TAGS: Record<string, string> = {
  bg: "Сменить фон: `bg: gym`",
  show: "Показать персонажа: `show: anna happy [left|center|right]`",
  hide: "Убрать персонажа: `hide: anna`",
  music: "Фоновая музыка: `music: upbeat` или `music: stop`",
  sfx: "Звуковой эффект: `sfx: door_slam`",
  wait: "Пауза до 10 секунд: `wait: 1.5`",
  fx: "Встряска или вспышка: `fx: shake`, `fx: flash`",
  effect: "Изменить состояние игры: `effect: affection anna +3`",
  premium: "Платный выбор, внутри [скобок]: `premium: 15`",
};

export const EFFECTS: Record<string, string> = {
  affection: "Симпатия: `affection anna +3`",
  stat: "Характеристика: `stat charm +2`",
  give: "Дать предмет: `give rose [2]`",
  take: "Забрать предмет: `take rose [2]`",
  flag: "Поставить флаг: `flag met_anna`",
  unflag: "Снять флаг: `unflag met_anna`",
  start_quest: "Начать квест: `start_quest anna_trust`",
  advance_quest: "Закрыть этап квеста: `advance_quest anna_trust`",
  xp: "Опыт аккаунта: `xp 10`",
  achievement: "Достижение: `achievement first_date`",
};

export const FUNCTIONS: Record<string, string> = {
  affection: 'Симпатия персонажа: `affection("anna")`',
  has: 'Есть ли предмет: `has("rose")`',
  flag: 'Стоит ли флаг: `flag("met_anna")`',
  stat: 'Характеристика: `stat("charm")`',
  global_level: "Уровень аккаунта игрока: `global_level()`",
};

export interface Suggestion {
  label: string;
  /** Что вставить; по умолчанию label. */
  insert?: string;
  detail?: string;
  documentation?: string;
  kind: "tag" | "key" | "character" | "node" | "function" | "value";
  /** Сразу открыть подсказки для следующего аргумента. */
  retrigger?: boolean;
}

export interface Completion {
  /** Сколько символов перед курсором заменяет подсказка. */
  replace: number;
  items: Suggestion[];
}

const keys = (
  names: Record<string, string>,
  kind: Suggestion["kind"] = "key",
  retrigger = false,
): Suggestion[] =>
  Object.entries(names).map(([key, name]) => ({
    label: key,
    detail: name === key ? undefined : name,
    kind,
    retrigger,
  }));

const list = (values: string[], kind: Suggestion["kind"] = "key"): Suggestion[] =>
  values.map((value) => ({ label: value, kind }));

const characterNames = (context: SceneContext) =>
  Object.fromEntries(Object.entries(context.characters).map(([key, c]) => [key, c.name]));

function tagArgument(name: string, args: string[], context: SceneContext): Suggestion[] | null {
  const index = args.length - 1;
  switch (name) {
    case "bg":
      return index === 0 ? list(context.backgrounds) : null;
    case "show":
      if (index === 0) return keys(characterNames(context), "character", true);
      if (index === 1) {
        return list(context.characters[args[0]!]?.emotions ?? []).map((s) => ({
          ...s,
          retrigger: true,
        }));
      }
      return index === 2 ? list(["left", "center", "right"], "value") : null;
    case "hide":
      return index === 0 ? keys(characterNames(context), "character") : null;
    case "music":
      return index === 0 ? [...list(context.music), { label: "stop", kind: "value" }] : null;
    case "sfx":
      return index === 0 ? list(context.sfx) : null;
    case "fx":
      return index === 0 ? list(["shake", "flash"], "value") : null;
    case "effect":
      return effectArgument(args, context);
    default:
      return null;
  }
}

function effectArgument(args: string[], context: SceneContext): Suggestion[] | null {
  const index = args.length - 1;
  if (index === 0) {
    return Object.entries(EFFECTS).map(([op, documentation]) => ({
      label: op,
      insert: `${op} `,
      documentation,
      kind: "tag",
      retrigger: op !== "xp",
    }));
  }
  if (index !== 1) return null;
  switch (args[0]) {
    case "affection":
      return keys(characterNames(context), "character");
    case "stat":
      return keys(context.stats);
    case "give":
    case "take":
      return keys(context.items);
    case "flag":
    case "unflag":
      return list(context.flags);
    case "start_quest":
    case "advance_quest":
      return keys(context.quests);
    case "achievement":
      return keys(context.achievements);
    default:
      return null;
  }
}

// Последний тег в строке: `[^#]` не даёт захватить предыдущий.
const TAG_AT_END = /#\s*([a-z_]*)(?:\s*:\s*([^#]*))?$/;
const DIVERT_AT_END = /(?:->|<-)\s*([\w.]*)$/;
const CALL_AT_END = /\b(affection|has|flag|stat)\(\s*"([a-z0-9_]*)$/;
const LINE_START = /^\s*(?:[-*+]\s*)*([a-z][a-z0-9_]*)?$/;
// Место для функции в логике: после `{`, `(`, `~`, and/or/not и операторов — не в тексте условия.
const LOGIC_AT_END = /(?:^\s*~|[{(]|\b(?:and|or|not)\s|[!&|<>=]=?)\s*([a-z_]*)$/;

/** Подсказки по тексту строки до курсора; null — подсказывать нечего. */
export function complete(before: string, source: string, context: SceneContext): Completion | null {
  const tag = TAG_AT_END.exec(before);
  if (tag) {
    const [, name = "", rest] = tag;
    if (rest === undefined) {
      return {
        replace: name.length,
        items: Object.entries(TAGS).map(([label, documentation]) => ({
          label,
          insert: `${label}: `,
          documentation,
          kind: "tag",
          retrigger: label !== "wait" && label !== "premium",
        })),
      };
    }
    const args = rest.split(/\s+/);
    const items = tagArgument(name, args, context);
    if (!items) return null;
    const partial = args[args.length - 1]!;
    return {
      replace: partial.length,
      items: items.map((s) => (s.retrigger && !s.insert ? { ...s, insert: `${s.label} ` } : s)),
    };
  }

  const divert = DIVERT_AT_END.exec(before);
  if (divert) {
    const targets: Suggestion[] = outline(source)
      .filter((node) => node.kind !== "function")
      .map((node) => ({ label: node.path, detail: `строка ${node.line}`, kind: "node" }));
    return {
      replace: divert[1]!.length,
      items: [...targets, { label: "END", kind: "value", detail: "конец сцены" }],
    };
  }

  const call = CALL_AT_END.exec(before);
  if (call) {
    const [, fn, partial = ""] = call;
    const items =
      fn === "affection"
        ? keys(characterNames(context), "character")
        : fn === "has"
          ? keys(context.items)
          : fn === "stat"
            ? keys(context.stats)
            : list(context.flags);
    return { replace: partial.length, items };
  }

  const opened = (before.match(/\{/g)?.length ?? 0) > (before.match(/\}/g)?.length ?? 0);
  const logic = LOGIC_AT_END.exec(before);
  if (logic && (opened || /^\s*~/.test(before))) {
    const partial = logic[1]!;
    return {
      replace: partial.length,
      items: Object.entries(FUNCTIONS).map(([name, documentation]) => ({
        label: name,
        insert: name === "global_level" ? "global_level()" : `${name}("`,
        documentation,
        kind: "function",
        retrigger: name !== "global_level",
      })),
    };
  }

  const start = LINE_START.exec(before);
  if (start?.[1]) {
    return {
      replace: start[1].length,
      items: [
        ...keys(characterNames(context), "character").map((s) => ({
          ...s,
          insert: `${s.label}: `,
        })),
        { label: "me", insert: "me: ", detail: "протагонист", kind: "character" },
      ],
    };
  }
  return null;
}
