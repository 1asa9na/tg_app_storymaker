// Компиляция сцены: ink → JSON для inkjs + белый список эффектов + диагностика.
// Тяжёлый компилятор inkjs нужен только здесь, поэтому модуль подключается отдельно
// (`@storymaker/engine/compile`): плеер его не грузит.
import { Compiler } from "inkjs/full";

import { parseTag, TagError, type Command, type Effect } from "./tags.ts";

/** Функции чтения состояния игры. Сценаристу не нужно их объявлять: заголовок добавляется сам. */
export const EXTERNAL_FUNCTIONS = ["affection", "has", "flag", "stat", "global_level"] as const;

const HEADER = [
  "EXTERNAL affection(who)",
  "EXTERNAL has(item)",
  "EXTERNAL flag(name)",
  "EXTERNAL stat(name)",
  "EXTERNAL global_level()",
].join("\n");
const HEADER_LINES = HEADER.split("\n").length;
const OWN_EXTERNAL = new RegExp(`^\\s*EXTERNAL\\s+(${EXTERNAL_FUNCTIONS.join("|")})\\s*\\(`);
const SPEAKER = /^([a-z][a-z0-9_]*):\s/;
/** Реплика протагониста: его имя задаёт игрок, в реестре персонажей его нет. */
export const PLAYER_SPEAKER = "me";

export interface Diagnostic {
  severity: "error" | "warning";
  /** Строка в исходнике сцены (с 1) или null, если её не удалось определить. */
  line: number | null;
  message: string;
}

/** Известные ключи тайтла. Пустое поле — проверка этого вида ключей пропускается. */
export interface Registry {
  /** Персонаж → список его эмоций. */
  characters?: Record<string, string[]>;
  backgrounds?: string[];
  music?: string[];
  sfx?: string[];
  items?: string[];
  stats?: string[];
  quests?: string[];
  achievements?: string[];
}

export interface CompiledScene {
  /** JSON для `new Story(json)`. */
  json: string;
  /** Все эффекты, которые может вернуть сцена: сервер применяет только их. */
  effects: Effect[];
}

export interface CompileResult {
  /** null, если есть ошибки. */
  scene: CompiledScene | null;
  diagnostics: Diagnostic[];
}

type InkJson = string | number | boolean | null | InkJson[] | { [key: string]: InkJson };

interface Collected {
  tags: string[];
  dynamicTags: number;
  speakers: string[];
}

/** Обходит скомпилированный JSON: статические теги (`"#", "^текст", "/#"`) и реплики. */
function collect(node: InkJson, out: Collected): void {
  if (Array.isArray(node)) {
    for (let i = 0; i < node.length; i++) {
      const item = node[i];
      if (item === "#") {
        const end = node.indexOf("/#", i);
        const body = end === -1 ? [] : node.slice(i + 1, end);
        const [text] = body;
        if (body.length === 1 && typeof text === "string" && text.startsWith("^")) {
          out.tags.push(text.slice(1).trim());
        } else {
          out.dynamicTags++;
        }
        i = end === -1 ? i : end;
        continue;
      }
      if (typeof item === "string" && item.startsWith("^")) {
        const speaker = SPEAKER.exec(item.slice(1));
        if (speaker?.[1]) {
          out.speakers.push(speaker[1]);
        }
      }
      collect(item ?? null, out);
    }
  } else if (node !== null && typeof node === "object") {
    for (const value of Object.values(node)) {
      collect(value, out);
    }
  }
}

function lineOf(source: string, needle: string): number | null {
  const index = source.split("\n").findIndex((line) => line.includes(needle));
  return index === -1 ? null : index + 1;
}

/** Строки, где стоит именно этот тег: `# show: anna` не совпадёт с `# show: anna happy`. */
function tagLines(source: string, tag: string): (number | null)[] {
  const lines: number[] = [];
  source.split("\n").forEach((line, index) => {
    const tags = line
      .replace(/\/\/.*$/, "")
      .split("#")
      .slice(1);
    // Тег внутри [выбора] кончается на скобке: `* [Позвать #premium: 15]`.
    if (tags.some((part) => part.replace(/\].*$/, "").trim() === tag)) lines.push(index + 1);
  });
  return lines.length ? lines : [lineOf(source, tag)];
}

/** Первая строка с репликой персонажа: `anna: …`, в том числе после `-` или `*`. */
function speakerLine(source: string, speaker: string): number | null {
  const pattern = new RegExp(`^\\s*(?:[-*+]\\s*)*${speaker}:\\s`);
  const index = source.split("\n").findIndex((line) => pattern.test(line));
  return index === -1 ? lineOf(source, `${speaker}:`) : index + 1;
}

/** "ERROR: line 13: ..." → номер строки исходника (без добавленного заголовка) и текст. */
function parseCompilerMessage(raw: string): { line: number | null; message: string } {
  const match = /line (\d+): (.*)$/s.exec(raw);
  if (!match?.[1] || match[2] === undefined) {
    return { line: null, message: raw.replace(/^(ERROR|WARNING|TODO):\s*/, "") };
  }
  return { line: Math.max(1, Number(match[1]) - HEADER_LINES), message: match[2] };
}

function checkKey(
  known: readonly string[] | undefined,
  value: string,
  what: string,
): string | null {
  return known === undefined || known.includes(value) ? null : `${what} «${value}» нет в тайтле`;
}

function checkCommand(command: Command, registry: Registry): string | null {
  const characters = registry.characters;
  switch (command.type) {
    case "bg":
      return checkKey(registry.backgrounds, command.key, "Фона");
    case "show": {
      if (characters === undefined) {
        return null;
      }
      const emotions = characters[command.character];
      if (emotions === undefined) {
        return `Персонажа «${command.character}» нет в тайтле`;
      }
      return emotions.includes(command.emotion)
        ? null
        : `У персонажа «${command.character}» нет эмоции «${command.emotion}»`;
    }
    case "hide":
      return characters === undefined
        ? null
        : checkKey(Object.keys(characters), command.character, "Персонажа");
    case "music":
      return command.key === null ? null : checkKey(registry.music, command.key, "Трека");
    case "sfx":
      return checkKey(registry.sfx, command.key, "Звука");
    case "wait":
    case "fx":
      return null;
  }
}

function checkEffect(effect: Effect, registry: Registry): string | null {
  switch (effect.op) {
    case "affection":
      return registry.characters === undefined
        ? null
        : checkKey(Object.keys(registry.characters), effect.character, "Персонажа");
    case "stat":
      return checkKey(registry.stats, effect.stat, "Характеристики");
    case "give":
    case "take":
      return checkKey(registry.items, effect.item, "Предмета");
    case "start_quest":
    case "advance_quest":
      return checkKey(registry.quests, effect.quest, "Квеста");
    case "achievement":
      return checkKey(registry.achievements, effect.key, "Достижения");
    case "flag":
    case "xp":
      return null;
  }
}

export function compileScene(source: string, registry: Registry = {}): CompileResult {
  const diagnostics: Diagnostic[] = [];
  // Свои объявления EXTERNAL сценаристу не нужны; заменяем пустой строкой, чтобы не сбить нумерацию.
  const body = source
    .split("\n")
    .map((line, index) => {
      if (!OWN_EXTERNAL.test(line)) {
        return line;
      }
      diagnostics.push({
        severity: "warning",
        line: index + 1,
        message: "EXTERNAL-функции объявлять не нужно, строка пропущена",
      });
      return "";
    })
    .join("\n");

  const compiler = new Compiler(`${HEADER}\n${body}`);
  let json: string | null = null;
  try {
    json = compiler.Compile().ToJson() ?? null;
  } catch {
    // Ошибки уже собраны в compiler.errors.
  }
  for (const raw of compiler.errors) {
    diagnostics.push({ severity: "error", ...parseCompilerMessage(raw) });
  }
  for (const raw of compiler.warnings) {
    diagnostics.push({ severity: "warning", ...parseCompilerMessage(raw) });
  }
  if (json === null) {
    if (compiler.errors.length === 0) {
      diagnostics.push({ severity: "error", line: null, message: "Сцена не скомпилировалась" });
    }
    return { scene: null, diagnostics };
  }

  const collected: Collected = { tags: [], dynamicTags: 0, speakers: [] };
  collect(JSON.parse(json) as InkJson, collected);

  if (collected.dynamicTags > 0) {
    diagnostics.push({
      severity: "error",
      line: null,
      message:
        "В тегах нельзя использовать выражения и переменные: значения должны быть записаны прямо в теге",
    });
  }

  const effects = new Map<string, Effect>();
  for (const text of new Set(collected.tags)) {
    let problem: string | null;
    try {
      const tag = parseTag(text);
      problem =
        tag.kind === "command"
          ? checkCommand(tag.command, registry)
          : tag.kind === "effect"
            ? checkEffect(tag.effect, registry)
            : null;
      if (tag.kind === "effect") {
        effects.set(JSON.stringify(tag.effect), tag.effect);
      }
    } catch (error) {
      if (!(error instanceof TagError)) {
        throw error;
      }
      problem = `#${text}: ${error.message}`;
    }
    if (problem !== null) {
      for (const line of tagLines(source, text)) {
        diagnostics.push({ severity: "error", line, message: problem });
      }
    }
  }

  const characters = registry.characters;
  if (characters !== undefined) {
    for (const speaker of new Set(collected.speakers)) {
      if (speaker !== PLAYER_SPEAKER && !(speaker in characters)) {
        diagnostics.push({
          severity: "error",
          line: speakerLine(source, speaker),
          message: `Говорит персонаж «${speaker}», которого нет в тайтле`,
        });
      }
    }
  }

  const failed = diagnostics.some((diagnostic) => diagnostic.severity === "error");
  return { scene: failed ? null : { json, effects: [...effects.values()] }, diagnostics };
}
