// Исполнение скомпилированной сцены: inkjs → поток шагов для рендерера.
// Рендерер про ink ничего не знает: он получает реплики, выборы и команды.
import { Story } from "inkjs";

import { parseTag, TagError, type Command, type Effect } from "./tags.ts";

/** Состояние игры, которое сцена видит через EXTERNAL-функции. Только для чтения. */
export interface GameSnapshot {
  affection?: Record<string, number>;
  items?: Record<string, number>;
  flags?: Record<string, boolean>;
  stats?: Record<string, number>;
  globalLevel?: number;
}

export interface SceneChoice {
  index: number;
  text: string;
  /** Цена в кристаллах для платного выбора. */
  premium: number | null;
}

export type Step =
  | { type: "line"; speaker: string | null; text: string; commands: Command[] }
  | { type: "choices"; choices: SceneChoice[]; commands: Command[] }
  | { type: "end"; commands: Command[]; effects: Effect[] };

interface View {
  affection: Record<string, number>;
  items: Record<string, number>;
  flags: Record<string, boolean>;
  stats: Record<string, number>;
  globalLevel: number;
}

const SPEAKER = /^([a-z][a-z0-9_]*):\s+(.*)$/s;

function applyEffect(view: View, effect: Effect): void {
  switch (effect.op) {
    case "affection":
      view.affection[effect.character] = (view.affection[effect.character] ?? 0) + effect.delta;
      break;
    case "stat":
      view.stats[effect.stat] = (view.stats[effect.stat] ?? 0) + effect.delta;
      break;
    case "give":
      view.items[effect.item] = (view.items[effect.item] ?? 0) + effect.count;
      break;
    case "take":
      view.items[effect.item] = Math.max(0, (view.items[effect.item] ?? 0) - effect.count);
      break;
    case "flag":
      view.flags[effect.flag] = effect.value;
      break;
    case "start_quest":
    case "advance_quest":
    case "xp":
    case "achievement":
      // На состояние, видимое сцене, не влияют: их применяет сервер.
      break;
  }
}

export class SceneRunner {
  private readonly story: Story;
  private readonly view: View;
  private readonly effects: Effect[] = [];
  /** Сообщение для каждого тега, который не удалось разобрать (в студии такое ловит линтер). */
  readonly warnings: string[] = [];

  constructor(json: string, snapshot: GameSnapshot = {}) {
    this.story = new Story(json);
    this.view = {
      affection: { ...snapshot.affection },
      items: { ...snapshot.items },
      flags: { ...snapshot.flags },
      stats: { ...snapshot.stats },
      globalLevel: snapshot.globalLevel ?? 0,
    };
    // lookaheadSafe = false: ink не вызывает функцию заранее, пока мы не применили
    // эффекты из тегов предыдущих строк, поэтому has() после take видит актуальное значение.
    const view = this.view;
    this.story.BindExternalFunction("affection", (who: string) => view.affection[who] ?? 0, false);
    this.story.BindExternalFunction("has", (item: string) => (view.items[item] ?? 0) > 0, false);
    this.story.BindExternalFunction("flag", (name: string) => view.flags[name] ?? false, false);
    this.story.BindExternalFunction("stat", (name: string) => view.stats[name] ?? 0, false);
    this.story.BindExternalFunction("global_level", () => view.globalLevel, false);
  }

  /** Эффекты, накопленные с начала сцены; в конце они уходят на сервер. */
  get collectedEffects(): readonly Effect[] {
    return this.effects;
  }

  /** Начать с конкретного узла (`=== knot ===`) вместо начала сцены: для превью в студии. */
  startAt(path: string): void {
    this.story.ChoosePathString(path);
  }

  next(): Step {
    const commands: Command[] = [];
    while (this.story.canContinue) {
      const text = (this.story.Continue() ?? "").trim();
      commands.push(...this.consumeTags(this.story.currentTags ?? []));
      if (text) {
        const speaker = SPEAKER.exec(text);
        return speaker?.[1] && speaker[2] !== undefined
          ? { type: "line", speaker: speaker[1], text: speaker[2], commands }
          : { type: "line", speaker: null, text, commands };
      }
    }
    const choices = this.story.currentChoices;
    if (choices.length > 0) {
      return {
        type: "choices",
        commands,
        choices: choices.map((choice) => ({
          index: choice.index,
          text: choice.text,
          premium: this.premiumOf(choice.tags ?? []),
        })),
      };
    }
    return { type: "end", commands, effects: [...this.effects] };
  }

  choose(index: number): void {
    this.story.ChooseChoiceIndex(index);
  }

  /** Сохранение посреди сцены: состояние ink и накопленные эффекты. */
  save(): string {
    return JSON.stringify({ ink: this.story.state.ToJson(), effects: this.effects });
  }

  /** Восстановление сохранения поверх того же скомпилированного JSON и снимка. */
  restore(saved: string): void {
    const data = JSON.parse(saved) as { ink: string; effects: Effect[] };
    this.story.state.LoadJson(data.ink);
    for (const effect of data.effects) {
      this.effects.push(effect);
      applyEffect(this.view, effect);
    }
  }

  private consumeTags(tags: string[]): Command[] {
    const commands: Command[] = [];
    for (const raw of tags) {
      const tag = this.parse(raw);
      if (tag?.kind === "command") {
        commands.push(tag.command);
      } else if (tag?.kind === "effect") {
        this.effects.push(tag.effect);
        applyEffect(this.view, tag.effect);
      }
      // premium на строке — это текст выбора без скобок, показанный после выбора: цену уже учли.
    }
    return commands;
  }

  private premiumOf(tags: string[]): number | null {
    for (const raw of tags) {
      const tag = this.parse(raw);
      if (tag?.kind === "premium") {
        return tag.price;
      }
    }
    return null;
  }

  private parse(raw: string) {
    try {
      return parseTag(raw);
    } catch (error) {
      if (!(error instanceof TagError)) {
        throw error;
      }
      this.warnings.push(`#${raw}: ${error.message}`);
      return null;
    }
  }
}
