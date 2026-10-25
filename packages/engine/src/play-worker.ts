// Проигрывание сцен без интерфейса — для симулятора баланса на сервере.
// Один процесс на всю симуляцию: запрос — строка JSON на stdin, ответ — строка JSON на stdout.
//   {"id": 1, "json": "<скомпилированная сцена>", "snapshot": {...}, "strategy": "first", "seed": 7}
//   → {"id": 1, "effects": [...]}  или  {"id": 1, "error": "..."}
// Стратегии выбора: first — всегда первый вариант, random — случайный,
// free — случайный среди бесплатных (игрок, который не тратит кристаллы).
import { createInterface } from "node:readline";

import { SceneRunner, type GameSnapshot, type SceneChoice } from "./runtime.ts";

type Strategy = "first" | "random" | "free";

interface Request {
  id: number;
  json: string;
  snapshot?: GameSnapshot;
  strategy?: Strategy;
  seed?: number;
}

/** Детерминированный генератор mulberry32: одинаковый seed — одинаковые выборы. */
function random(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pick(choices: SceneChoice[], strategy: Strategy, next: () => number): SceneChoice {
  const pool = strategy === "free" ? choices.filter((choice) => choice.premium === null) : choices;
  const options = pool.length > 0 ? pool : choices;
  if (strategy === "first") {
    return options[0]!;
  }
  return options[Math.floor(next() * options.length)]!;
}

function play(request: Request): unknown[] {
  const runner = new SceneRunner(request.json, request.snapshot ?? {});
  const next = random(request.seed ?? 1);
  for (let guard = 0; guard < 10_000; guard++) {
    const step = runner.next();
    if (step.type === "end") {
      return step.effects;
    }
    if (step.type === "choices") {
      runner.choose(pick(step.choices, request.strategy ?? "first", next).index);
    }
  }
  throw new Error("сцена не закончилась за 10 000 шагов");
}

const lines = createInterface({ input: process.stdin });
lines.on("line", (line) => {
  if (!line.trim()) {
    return;
  }
  let id: number | null = null;
  try {
    const request = JSON.parse(line) as Request;
    id = request.id;
    process.stdout.write(`${JSON.stringify({ id, effects: play(request) })}\n`);
  } catch (error) {
    process.stdout.write(`${JSON.stringify({ id, error: (error as Error).message })}\n`);
  }
});
