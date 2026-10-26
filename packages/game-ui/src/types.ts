// Ответы API тайтла (docs/API.md). Поля — как их отдаёт сервер.

export interface Named {
  name: string;
}

export interface GameData {
  slug: string;
  name: string;
  build: string;
  time: { slots: { id: string; name: string }[]; days: number | null; week: string[] | null };
  resources: Record<string, { name: string; max: number | null }>;
  stats: Record<string, { name: string; min: number; max: number }>;
  characters: Record<
    string,
    {
      name: string;
      color: string | null;
      emotions: string[];
      romance: boolean;
      levels: { at: number; name: string }[];
    }
  >;
  gifts_per_day: number;
  map: { image: string | null; points: Record<string, { x: number; y: number }> };
  locations: Record<string, { name: string; background: string }>;
  items: Record<
    string,
    { name: string; description: string; icon: string | null; kind: "gift" | "consumable" | "key" }
  >;
  quests: Record<string, { name: string; stages: { id: string; journal: string }[] }>;
  achievements: Record<string, { name: string; description: string }>;
}

export interface Account {
  xp: number;
  level: number;
  level_xp: number;
  next_level_xp: number;
  level_up: boolean;
}

export interface SaveState {
  day: number;
  slot: number;
  location: string | null;
  stats: Record<string, number>;
  affection: Record<string, number>;
  items: Record<string, number>;
  flags: Record<string, boolean>;
  quests: Record<string, { status: "active" | "done"; stage: number }>;
  gifts_today: Record<string, number>;
  global_level: number;
  finished: boolean;
}

export interface Activity {
  id: string;
  name: string;
  description: string;
  cost: Record<string, number>;
  effects: Record<string, number>;
  with_character: string | null;
  lock: string | null;
}

export interface View {
  revision: number;
  account: Account;
  state: SaveState;
  time: { day: number; slot: string; weekday: string | null };
  resources: Record<string, { value: number; max: number | null; next_at: string | null }>;
  locations: {
    id: string;
    name: string;
    point: { x: number; y: number } | null;
    lock: string | null;
    characters: string[];
  }[];
  here: { location: string | null; characters: string[]; activities: Activity[] };
  can_sleep: boolean;
  pending_scene: string | null;
}

export interface Change {
  path: string;
  delta: number;
}

export interface Outcome {
  changes: Change[];
  scenes: string[];
  xp: number;
  achievements: string[];
  quests: { quest: string; status: "active" | "done"; stage: string | null }[];
  new_day: boolean;
}

export type ActionResult = View & { outcome: Outcome };

export type Action =
  | { type: "go"; location: string }
  | { type: "leave" }
  | { type: "activity"; id: string }
  | { type: "gift"; item: string; character: string }
  | { type: "use"; item: string }
  | { type: "sleep" }
  | { type: "scene_complete"; scene: string; effects: unknown[] };

/** Отказ сервера: действие не принято, состояние не изменилось. */
export class GameError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

/** Как экран игры ходит на сервер. Плеер ходит в API, песочница студии — в свою. */
export interface GameClient {
  game(): Promise<GameData>;
  state(): Promise<View>;
  act(action: Action, revision: number): Promise<ActionResult>;
  scene(key: string): Promise<{ key: string; json: string }>;
  restart(revision: number): Promise<View>;
}

export type Haptic = "tap" | "success" | "error";
