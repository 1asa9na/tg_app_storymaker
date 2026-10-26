import { describe, expect, it } from "vitest";

import { countdown, describeOutcome, formatCost, relationLevel, sumChanges } from "./format.ts";
import type { GameData } from "./types.ts";

const game = {
  stats: { fitness: { name: "Форма", min: 0, max: 100 } },
  resources: { energy: { name: "Энергия", max: 100 }, money: { name: "Деньги", max: null } },
  characters: {
    anna: { name: "Анна", color: null, emotions: ["neutral"], romance: true, levels: [] },
  },
  items: { rose: { name: "Роза", description: "", icon: null, kind: "gift" } },
  quests: {
    trust: {
      name: "Доверие",
      stages: [
        { id: "talk", journal: "Поговорить" },
        { id: "gift", journal: "Подарить" },
      ],
    },
  },
  achievements: { close: { name: "Близкие", description: "" } },
} as unknown as GameData;

describe("format", () => {
  it("describes an outcome for the player", () => {
    const lines = describeOutcome(
      {
        changes: [
          { path: "stat.fitness", delta: 3 },
          { path: "resource.energy", delta: -20 },
          { path: "affection.anna", delta: 2 },
        ],
        scenes: [],
        xp: 5,
        achievements: ["close"],
        quests: [
          { quest: "trust", status: "active", stage: "talk" },
          { quest: "trust", status: "active", stage: "gift" },
          { quest: "trust", status: "done", stage: null },
        ],
        new_day: false,
      },
      game,
    );

    expect(lines).toEqual([
      "Форма +3",
      "Энергия −20",
      "Анна ♥ +2",
      "Опыт +5",
      "Новый квест: Доверие",
      "Квест обновлён: Доверие",
      "Квест выполнен: Доверие",
      "Достижение: Близкие",
    ]);
  });

  it("formats activity cost", () => {
    expect(formatCost({ slots: 1, energy: 20, money: 0 }, game)).toEqual([
      "часть дня",
      "Энергия −20",
    ]);
    expect(formatCost({ slots: 0, money: 15 }, game)).toEqual(["Деньги −15"]);
  });

  it("sums changes over a day and drops zeros", () => {
    expect(
      sumChanges([
        { path: "resource.energy", delta: -20 },
        { path: "stat.fitness", delta: 3 },
        { path: "resource.energy", delta: 20 },
        { path: "stat.fitness", delta: 2 },
      ]),
    ).toEqual([{ path: "stat.fitness", delta: 5 }]);
  });

  it("picks the relation level by threshold", () => {
    const levels = [
      { at: 0, name: "Незнакомка" },
      { at: 10, name: "Знакомая" },
    ];
    expect(relationLevel(levels, 9)).toBe("Незнакомка");
    expect(relationLevel(levels, 10)).toBe("Знакомая");
  });

  it("counts down to the next regen", () => {
    const now = Date.parse("2026-10-26T10:00:00Z");
    expect(countdown("2026-10-26T10:04:59Z", now)).toBe("4:59");
    expect(countdown("2026-10-26T09:00:00Z", now)).toBe("0:00");
  });
});
