import { describe, expect, it } from "vitest";

import { complete, nodeAt, outline, type SceneContext } from "./analysis";

const CONTEXT: SceneContext = {
  scenes: [],
  registry: {},
  characters: {
    anna: { name: "Анна", color: null, emotions: ["neutral", "happy"] },
    max: { name: "Макс", color: null, emotions: ["neutral"] },
  },
  items: { rose: "Роза" },
  stats: { charm: "Обаяние" },
  quests: { anna_trust: "Доверие Анны" },
  achievements: { first_date: "Первое свидание" },
  flags: ["met_anna"],
  backgrounds: ["gym", "park"],
  music: ["calm"],
  sfx: ["door"],
  locations: {},
  manifest: {},
};

const SOURCE = `Начало.
-> second
=== second ===
* (ask) [Спросить]
= inner
Текст.
=== function double(x) ===
~ return x * 2
=== third ===
- (done) Конец.
`;

const labels = (before: string, source = SOURCE) =>
  complete(before, source, CONTEXT)?.items.map((item) => item.label) ?? null;

describe("outline", () => {
  it("finds knots, stitches, labels and functions", () => {
    expect(outline(SOURCE).map((node) => [node.path, node.kind, node.line])).toEqual([
      ["second", "knot", 3],
      ["second.ask", "label", 4],
      ["second.inner", "stitch", 5],
      ["double", "function", 7],
      ["third", "knot", 9],
      ["third.done", "label", 10],
    ]);
  });

  it("knows which node a line belongs to", () => {
    const nodes = outline(SOURCE);
    expect(nodeAt(nodes, 1)).toBeNull();
    expect(nodeAt(nodes, 4)?.path).toBe("second");
    expect(nodeAt(nodes, 6)?.path).toBe("second.inner");
    expect(nodeAt(nodes, 8)).toBeNull();
    expect(nodeAt(nodes, 10)?.path).toBe("third");
  });
});

describe("complete", () => {
  it("suggests tags after #", () => {
    const result = complete("# sh", SOURCE, CONTEXT);
    expect(result?.replace).toBe(2);
    expect(result?.items.find((item) => item.label === "show")?.insert).toBe("show: ");
  });

  it("walks the arguments of show", () => {
    expect(labels("# show: ")).toEqual(["anna", "max"]);
    expect(labels("# show: anna ")).toEqual(["neutral", "happy"]);
    expect(labels("# show: anna happy ")).toEqual(["left", "center", "right"]);
    expect(labels("# show: anna happy left ")).toBeNull();
  });

  it("knows backgrounds, music and the last tag on the line", () => {
    expect(labels("# bg: g")).toEqual(["gym", "park"]);
    expect(labels("# music: ")).toEqual(["calm", "stop"]);
    expect(labels("# bg: gym # sfx: ")).toEqual(["door"]);
    expect(labels("* [Позвать #premium: 15] # effect: give ")).toEqual(["rose"]);
  });

  it("suggests effects and their keys", () => {
    expect(labels("# effect: ")).toContain("affection");
    expect(labels("# effect: affection ")).toEqual(["anna", "max"]);
    expect(labels("# effect: stat ")).toEqual(["charm"]);
    expect(labels("# effect: unflag ")).toEqual(["met_anna"]);
    expect(labels("# effect: start_quest ")).toEqual(["anna_trust"]);
    expect(labels("# effect: achievement ")).toEqual(["first_date"]);
  });

  it("suggests divert targets without functions", () => {
    expect(labels("-> ")).toEqual([
      "second",
      "second.ask",
      "second.inner",
      "third",
      "third.done",
      "END",
    ]);
    expect(complete("* [Да] -> sec", SOURCE, CONTEXT)?.replace).toBe(3);
  });

  it("suggests functions only where logic expects them", () => {
    expect(labels("{ ")).toContain("affection");
    expect(labels("~ x = ")).toContain("has");
    expect(labels("{ has(")).toContain("has");
    expect(labels('{ flag("met_anna"): Привет, ')).toBeNull();
    expect(labels('{ affection("')).toEqual(["anna", "max"]);
    expect(labels('{ has("r')).toEqual(["rose"]);
  });

  it("suggests speakers at the start of a line only", () => {
    expect(labels("an")).toEqual(["anna", "max", "me"]);
    expect(complete("- an", SOURCE, CONTEXT)?.items[0]?.insert).toBe("anna: ");
    expect(labels("Привет, ")).toBeNull();
    expect(labels("")).toBeNull();
  });
});
