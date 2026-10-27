import { describe, expect, it } from "vitest";

import { withPlaceholders } from "./placeholders.ts";
import type { GameData } from "./types.ts";

const game = {
  locations: {
    gym: { name: "Зал", background: "gym" },
    park: { name: "Парк", background: "park" },
  },
  characters: {
    anna: { name: "Анна", color: "#f19bb8", emotions: [], romance: true, levels: [] },
  },
  map: { image: "city", points: {} },
  assets: {
    background: { gym: { "1080": "/assets/gym.1080.webp", "720": "/assets/gym.720.webp" } },
    sprite: { anna: { happy: { "1800": "/assets/a.1800.webp", "1200": "/assets/a.1200.webp" } } },
    icon: { item_rose: { "256": "/assets/rose.256.webp" } },
    music: { calm: "/assets/calm.m4a" },
  },
} as unknown as GameData;

describe("withPlaceholders", () => {
  it("uses manifest files and falls back to placeholders", () => {
    const assets = withPlaceholders(game);

    expect(assets.background("gym")).toMatch(/^\/assets\/gym\.(1080|720)\.webp$/);
    expect(assets.background("park")).toMatch(/^data:image\/svg\+xml/);
    expect(assets.sprite("anna", "happy")).toMatch(/^\/assets\/a\.(1800|1200)\.webp$/);
    expect(assets.sprite("anna", "sad")).toMatch(/^data:image\/svg\+xml/);
    expect(assets.map("city")).toMatch(/^data:image\/svg\+xml/);
    expect(assets.icon("item_rose")).toBe("/assets/rose.256.webp");
    expect(assets.icon("item_none")).toBeUndefined();
    expect(assets.audio?.("music", "calm")).toBe("/assets/calm.m4a");
    expect(assets.audio?.("sfx", "door")).toBeUndefined();
  });
});
