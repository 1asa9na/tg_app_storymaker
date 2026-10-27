import type { AssetResolver } from "@storymaker/vn-renderer";

import type { GameData, Variants } from "./types.ts";

// Арт-заглушки, пока ассеты не загружены (этап 3): фон — градиент с названием места,
// спрайт — силуэт цвета персонажа. Цвет фона стабилен для ключа.

const svg = (body: string, width: number, height: number) =>
  `data:image/svg+xml;charset=utf-8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}">${body}</svg>`,
  )}`;

function hue(key: string): number {
  let hash = 0;
  for (const char of key) hash = (hash * 31 + char.charCodeAt(0)) % 360;
  return hash;
}

const escape = (text: string) =>
  text.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

export function placeholderBackground(key: string, label: string): string {
  const h = hue(key);
  return svg(
    `<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
       <stop offset="0" stop-color="hsl(${h},35%,32%)"/>
       <stop offset="1" stop-color="hsl(${(h + 40) % 360},30%,10%)"/></linearGradient></defs>
     <rect width="1080" height="1920" fill="url(#g)"/>
     <rect y="1350" width="1080" height="570" fill="hsl(${h},20%,12%)" opacity="0.7"/>
     <text x="540" y="300" font-size="72" fill="hsl(${h},40%,80%)" opacity="0.55"
       text-anchor="middle" font-family="sans-serif">${escape(label)}</text>`,
    1080,
    1920,
  );
}

const MOUTHS: Record<string, string> = {
  happy: `<path d="M145 205 q35 35 70 0" stroke="#5b2a3a" stroke-width="7" fill="none" stroke-linecap="round"/>`,
  smirk: `<path d="M150 218 q35 6 62 -14" stroke="#5b2a3a" stroke-width="7" fill="none" stroke-linecap="round"/>`,
  sad: `<path d="M148 222 q32 -22 64 0" stroke="#5b2a3a" stroke-width="7" fill="none" stroke-linecap="round"/>`,
};
const NEUTRAL = `<path d="M150 214 h60" stroke="#5b2a3a" stroke-width="7" stroke-linecap="round"/>`;

export function placeholderSprite(color: string, emotion: string): string {
  return svg(
    `<path d="M70 340 q110 -70 220 0 l40 660 h-300 z" fill="${color}"/>
     <circle cx="180" cy="180" r="105" fill="#f2d2c0"/>
     <path d="M70 175 q10 -140 110 -140 q100 0 110 140 q-30 -70 -110 -80 q-80 10 -110 80" fill="#3b2420"/>
     <circle cx="145" cy="170" r="10" fill="#2a1a22"/><circle cx="215" cy="170" r="10" fill="#2a1a22"/>
     ${MOUTHS[emotion] ?? NEUTRAL}`,
    360,
    1000,
  );
}

/** Ассеты экрана игры: сцены (AssetResolver рендерера) плюс карта и иконки. */
export interface GameAssets extends AssetResolver {
  map(key: string): string;
  icon(key: string): string | undefined;
}

/** Вариант по экрану: крупный — для плотных экранов, мелкий — для остальных. */
function pick(variants: Variants | undefined, large: string, small: string): string | undefined {
  if (!variants) return undefined;
  const pixels =
    typeof window === "undefined" ? Infinity : window.innerWidth * (window.devicePixelRatio || 1);
  return (pixels > 600 ? variants[large] : variants[small]) ?? Object.values(variants)[0];
}

/** Ассеты тайтла: из манифеста сборки, чего нет — заглушки. `override` — для песочницы. */
export function withPlaceholders(game: GameData, override?: Partial<AssetResolver>): GameAssets {
  const manifest = game.assets ?? {};
  const names = new Map(
    Object.values(game.locations).map((location) => [location.background, location.name]),
  );
  return {
    background: (key) =>
      override?.background?.(key) ??
      pick(manifest.background?.[key], "1080", "720") ??
      placeholderBackground(key, names.get(key) ?? key),
    map: (key) =>
      pick(manifest.map?.[key], "1080", "720") ??
      manifest.background?.[key]?.["1080"] ??
      placeholderBackground(key, ""),
    sprite: (character, emotion) =>
      override?.sprite?.(character, emotion) ??
      pick(manifest.sprite?.[character]?.[emotion], "1800", "1200") ??
      placeholderSprite(game.characters[character]?.color ?? "#7d6aa8", emotion),
    icon: (key) => pick(manifest.icon?.[key], "256", "256"),
    audio: (kind, key) =>
      override?.audio?.(kind, key) ?? (kind === "music" ? manifest.music : manifest.sfx)?.[key],
  };
}
