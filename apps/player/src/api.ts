import {
  GameError,
  type Action,
  type ActionResult,
  type GameClient,
  type GameData,
  type View,
} from "@storymaker/game-ui/types";

export interface Me {
  id: number;
  tg_id: number;
  first_name: string;
  username: string | null;
  language_code: string | null;
  level: number;
  xp: number;
}

export interface CatalogEntry {
  slug: string;
  name: string;
  days: number | null;
  /** Обложка: {full, preview}; null — рисуем градиент. */
  cover: Record<string, string> | null;
  save: { day: number; finished: boolean } | null;
}

export interface Profile {
  xp: number;
  level: number;
  level_xp: number;
  next_level_xp: number;
  achievements: { key: string; name: string; title: string | null; unlocked_at: string }[];
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const RETRIES = 2;
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export class Api {
  readonly initData: string;

  constructor(initData: string) {
    this.initData = initData;
  }

  /**
   * Запрос к API. Обрыв сети повторяется с тем же телом: у действий в теле request_id,
   * и сервер применит действие один раз.
   */
  async request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
    for (let attempt = 0; ; attempt++) {
      let response: Response;
      try {
        response = await fetch(path, {
          method,
          headers: {
            Authorization: `tma ${this.initData}`,
            ...(body === undefined ? {} : { "Content-Type": "application/json" }),
          },
          body: body === undefined ? undefined : JSON.stringify(body),
        });
      } catch (error) {
        if (attempt >= RETRIES) throw error;
        await delay(500 * 2 ** attempt);
        continue;
      }
      if (response.status === 409) {
        const { detail } = (await response.json()) as { detail: { code: string; message: string } };
        throw new GameError(detail.code, detail.message);
      }
      if (response.status >= 500 && attempt < RETRIES) {
        await delay(500 * 2 ** attempt);
        continue;
      }
      if (!response.ok)
        throw new ApiError(response.status, `${method} ${path}: ${response.status}`);
      return (await response.json()) as T;
    }
  }

  me = () => this.request<Me>("GET", "/api/me");
  catalog = () => this.request<CatalogEntry[]>("GET", "/api/titles");
  profile = () => this.request<Profile>("GET", "/api/profile");

  title(slug: string): GameClient {
    return this.game(`/api/titles/${encodeURIComponent(slug)}`);
  }

  /** Песочница сборки по превью-ссылке из студии — только для команды. */
  preview(token: string): GameClient {
    return this.game(`/api/preview/${encodeURIComponent(token)}`);
  }

  private game(base: string): GameClient {
    return {
      game: () => this.request<GameData>("GET", `${base}/game`),
      state: () => this.request<View>("GET", `${base}/state`),
      act: (action: Action, revision: number) =>
        this.request<ActionResult>("POST", `${base}/actions`, {
          request_id: crypto.randomUUID(),
          revision,
          action,
        }),
      scene: (key: string) =>
        this.request<{ key: string; json: string }>(
          "GET",
          `${base}/scenes/${encodeURIComponent(key)}`,
        ),
      restart: (revision: number) =>
        this.request<View>("POST", `${base}/restart`, {
          request_id: crypto.randomUUID(),
          revision,
        }),
    };
  }
}
