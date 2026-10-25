import type { AssetResolver, CharacterInfo } from "@storymaker/vn-renderer";
import type { Registry } from "@storymaker/engine/compile";

// Арт-заглушки, пока нет настоящих ассетов: SVG рисуется прямо в коде.
const svg = (body: string, width: number, height: number) =>
  `data:image/svg+xml;charset=utf-8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}">${body}</svg>`,
  )}`;

const GYM = svg(
  `<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
     <stop offset="0" stop-color="#2b3a55"/><stop offset="1" stop-color="#121722"/></linearGradient></defs>
   <rect width="1080" height="1920" fill="url(#g)"/>
   <rect y="1300" width="1080" height="620" fill="#1a1f2b"/>
   <g fill="#3a4a66" opacity="0.6">
     <rect x="80" y="380" width="260" height="520" rx="12"/>
     <rect x="410" y="380" width="260" height="520" rx="12"/>
     <rect x="740" y="380" width="260" height="520" rx="12"/>
   </g>
   <text x="540" y="240" font-size="64" fill="#8fa3c7" text-anchor="middle"
     font-family="sans-serif">Спортзал (заглушка)</text>`,
  1080,
  1920,
);

const MOUTHS: Record<string, string> = {
  neutral: `<path d="M150 214 h60" stroke="#5b2a3a" stroke-width="7" stroke-linecap="round"/>`,
  happy: `<path d="M145 205 q35 35 70 0" stroke="#5b2a3a" stroke-width="7" fill="none" stroke-linecap="round"/>`,
  smirk: `<path d="M150 218 q35 6 62 -14" stroke="#5b2a3a" stroke-width="7" fill="none" stroke-linecap="round"/>`,
};

function anna(emotion: string): string {
  return svg(
    `<path d="M70 340 q110 -70 220 0 l40 660 h-300 z" fill="#b5476b"/>
     <circle cx="180" cy="180" r="105" fill="#f2d2c0"/>
     <path d="M70 175 q10 -140 110 -140 q100 0 110 140 q-30 -70 -110 -80 q-80 10 -110 80" fill="#3b2420"/>
     <circle cx="145" cy="170" r="10" fill="#2a1a22"/><circle cx="215" cy="170" r="10" fill="#2a1a22"/>
     ${MOUTHS[emotion] ?? MOUTHS.neutral}`,
    360,
    1000,
  );
}

export const demoAssets: AssetResolver = {
  background: (key) => (key === "gym" ? GYM : undefined),
  sprite: (character, emotion) => (character === "anna" ? anna(emotion) : undefined),
  audio: () => undefined,
};

export const demoCharacters: Record<string, CharacterInfo> = {
  anna: { name: "Анна", color: "#f19bb8" },
};

export const demoRegistry: Registry = {
  characters: { anna: Object.keys(MOUTHS) },
  backgrounds: ["gym"],
  music: ["upbeat"],
  items: ["water_bottle"],
  quests: ["anna_coffee"],
};
