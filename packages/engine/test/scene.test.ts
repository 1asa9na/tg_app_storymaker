import { describe, expect, it } from "vitest";

import { compileScene, type Registry } from "../src/compile.ts";
import { SceneRunner, type Step } from "../src/runtime.ts";

const SCENE = `# bg: gym
# music: upbeat
# show: anna neutral left
anna: Опять ты? Я начинаю думать, что это не совпадение.
# effect: flag met_anna

* { has("water_bottle") } [Предложить воду]
    # effect: take water_bottle
    # effect: affection anna +3
    # show: anna happy
    anna: О, спасибо. Ты внимательный.
* [Пошутить про тренера] # effect: affection anna +1
    anna: Ха. Только не при нём.
* { affection("anna") >= 20 } [Позвать на кофе #premium: 15]
    # effect: affection anna +5
    # effect: start_quest anna_coffee
    anna: …Давай. Но платишь ты.
- Зал постепенно пустел.
-> END
`;

const REGISTRY: Registry = {
  characters: { anna: ["neutral", "happy", "smirk"] },
  backgrounds: ["gym"],
  music: ["upbeat"],
  items: ["water_bottle"],
  quests: ["anna_coffee"],
};

function compiled(source = SCENE, registry = REGISTRY): string {
  const result = compileScene(source, registry);
  expect(result.diagnostics.filter((d) => d.severity === "error")).toEqual([]);
  return result.scene!.json;
}

function playUntilChoices(runner: SceneRunner): Step[] {
  const steps: Step[] = [];
  for (;;) {
    const step = runner.next();
    steps.push(step);
    if (step.type !== "line") {
      return steps;
    }
  }
}

describe("compileScene", () => {
  it("extracts the effect whitelist", () => {
    const result = compileScene(SCENE, REGISTRY);

    expect(result.scene?.effects).toEqual(
      expect.arrayContaining([
        { op: "flag", flag: "met_anna", value: true },
        { op: "take", item: "water_bottle", count: 1 },
        { op: "affection", character: "anna", delta: 3 },
        { op: "affection", character: "anna", delta: 1 },
        { op: "affection", character: "anna", delta: 5 },
        { op: "start_quest", quest: "anna_coffee" },
      ]),
    );
    expect(result.scene?.effects).toHaveLength(6);
  });

  it("reports ink errors at the writer's line numbers", () => {
    const source = 'Первая строка.\n{ has("rose"):\n    * [Выбор]\n}\n';

    const result = compileScene(source);

    expect(result.scene).toBeNull();
    expect(result.diagnostics[0]).toMatchObject({ severity: "error", line: 3 });
  });

  it("reports unknown keys from the registry", () => {
    const source = "# bg: beach\n# show: anna angry\n# effect: give rose\nboris: Привет.\n";

    const messages = compileScene(source, REGISTRY).diagnostics.map((d) => [d.line, d.message]);

    expect(messages).toEqual(
      expect.arrayContaining([
        [1, "Фона «beach» нет в тайтле"],
        [2, "У персонажа «anna» нет эмоции «angry»"],
        [3, "Предмета «rose» нет в тайтле"],
        [4, "Говорит персонаж «boris», которого нет в тайтле"],
      ]),
    );
  });

  it("points tag errors at every line with exactly that tag", () => {
    const source =
      "# show: anna neutral\nanna: Привет.\n# show: anna\nanna: Ну?\n# show: anna\n- anna: Пока.\n";

    const lines = compileScene(source, REGISTRY).diagnostics.map((d) => d.line);

    expect(lines).toEqual([3, 5]);
  });

  it("reports malformed tags and dynamic tags", () => {
    const result = compileScene("VAR x = 3\n# effect: affection anna 3\n# bg: {x}\nТекст.\n");

    expect(result.scene).toBeNull();
    expect(result.diagnostics.map((d) => d.message)).toEqual(
      expect.arrayContaining([
        expect.stringContaining("#effect: affection anna 3"),
        expect.stringContaining("нельзя использовать выражения"),
      ]),
    );
  });

  it("skips the writer's own EXTERNAL declarations with a warning", () => {
    const result = compileScene('EXTERNAL has(item)\n{ has("rose"): Есть роза. }\n');

    expect(result.scene).not.toBeNull();
    expect(result.diagnostics).toEqual([expect.objectContaining({ severity: "warning", line: 1 })]);
  });
});

describe("SceneRunner", () => {
  it("streams lines with speakers and commands, then choices", () => {
    const runner = new SceneRunner(compiled(), {
      items: { water_bottle: 1 },
      affection: { anna: 25 },
    });

    const steps = playUntilChoices(runner);

    expect(steps[0]).toEqual({
      type: "line",
      speaker: "anna",
      text: "Опять ты? Я начинаю думать, что это не совпадение.",
      commands: [
        { type: "bg", key: "gym" },
        { type: "music", key: "upbeat" },
        { type: "show", character: "anna", emotion: "neutral", position: "left" },
      ],
    });
    expect(steps.at(-1)).toEqual({
      type: "choices",
      commands: [],
      choices: [
        { index: 0, text: "Предложить воду", premium: null },
        { index: 1, text: "Пошутить про тренера", premium: null },
        { index: 2, text: "Позвать на кофе", premium: 15 },
      ],
    });
    expect(runner.collectedEffects).toEqual([{ op: "flag", flag: "met_anna", value: true }]);
  });

  it("hides choices whose conditions read the snapshot", () => {
    const runner = new SceneRunner(compiled(), {});

    const choices = playUntilChoices(runner).at(-1);

    expect(choices).toMatchObject({ choices: [{ text: "Пошутить про тренера" }] });
  });

  it("collects effects of the chosen branch and ends", () => {
    const runner = new SceneRunner(compiled(), { items: { water_bottle: 1 } });
    playUntilChoices(runner);

    runner.choose(0);
    const reply = runner.next();
    const narration = runner.next();
    const end = runner.next();

    expect(reply).toMatchObject({
      type: "line",
      speaker: "anna",
      commands: [{ type: "show", character: "anna", emotion: "happy", position: null }],
    });
    expect(narration).toMatchObject({
      type: "line",
      speaker: null,
      text: "Зал постепенно пустел.",
    });
    expect(end).toEqual({
      type: "end",
      commands: [],
      effects: [
        { op: "flag", flag: "met_anna", value: true },
        { op: "take", item: "water_bottle", count: 1 },
        { op: "affection", character: "anna", delta: 3 },
      ],
    });
  });

  it("lets conditions see effects applied earlier in the same scene", () => {
    const source = `Начало.
# effect: give rose
Тебе подарили розу.
* { has("rose") } [Понюхать розу]
    Пахнет летом.
* [Уйти]
    Пока.
- -> END
`;
    const runner = new SceneRunner(compiled(source, {}), {});

    const choices = playUntilChoices(runner).at(-1);

    expect(choices).toMatchObject({ choices: [{ text: "Понюхать розу" }, { text: "Уйти" }] });
  });

  it("reads affection after an affection effect in the same scene", () => {
    const source = `# effect: affection anna +20
Анна улыбнулась.
{ affection("anna") >= 20: Похоже, вы подружились. | Пока вы просто знакомые. }
-> END
`;
    const runner = new SceneRunner(compiled(source, {}), {});

    runner.next();
    const verdict = runner.next();

    expect(verdict).toMatchObject({ text: "Похоже, вы подружились." });
  });

  it("saves and restores mid-scene", () => {
    const json = compiled();
    const snapshot = { items: { water_bottle: 1 } };
    const first = new SceneRunner(json, snapshot);
    playUntilChoices(first);
    const saved = first.save();

    const second = new SceneRunner(json, snapshot);
    second.restore(saved);
    second.choose(1);
    second.next();
    second.next();
    const end = second.next();

    expect(end).toMatchObject({
      type: "end",
      effects: [
        { op: "flag", flag: "met_anna", value: true },
        { op: "affection", character: "anna", delta: 1 },
      ],
    });
  });
});
