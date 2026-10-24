// The badge art as data: one frame shape and palette per region, one glyph per badge. All of it is
// our own simple vector drawing (never a copy of any game sprite), so the icon component is a
// single renderer over these tables.

export type FrameId = "octagon" | "shield" | "hexagon" | "diamond" | "star";

export type Palette = {
  /** Frame gradient, top then bottom. */
  from: string;
  to: string;
  /** Frame outline. */
  edge: string;
  /** Glyph colour. */
  glyph: string;
};

export type RegionArt = { frame: FrameId; light: Palette; dark: Palette };

function starPath(): string {
  const pts: string[] = [];
  for (let i = 0; i < 10; i++) {
    const r = i % 2 === 0 ? 47 : 23;
    const a = (-90 + i * 36) * (Math.PI / 180);
    pts.push(`${(50 + r * Math.cos(a)).toFixed(1)} ${(53 + r * Math.sin(a)).toFixed(1)}`);
  }
  return `M${pts.join(" L")} Z`;
}

/** Frame outlines in a 100 x 100 box. */
export const FRAMES: Record<FrameId, string> = {
  octagon: "M30 6 H70 L94 30 V70 L70 94 H30 L6 70 V30 Z",
  shield: "M50 5 L90 18 V50 C90 74 72 90 50 96 C28 90 10 74 10 50 V18 Z",
  hexagon: "M50 4 L90 27 V73 L50 96 L10 73 V27 Z",
  diamond: "M50 3 L97 50 L50 97 L3 50 Z",
  star: starPath(),
};

export const REGION_ART: Record<string, RegionArt> = {
  // India: saffron and green
  kanto: {
    frame: "octagon",
    light: { from: "#ff9933", to: "#138808", edge: "#7a4a00", glyph: "#ffffff" },
    dark: { from: "#ffae4d", to: "#1fa012", edge: "#ffd7a0", glyph: "#ffffff" },
  },
  // US: blue and red
  johto: {
    frame: "shield",
    light: { from: "#2f5fd0", to: "#c8283c", edge: "#14306e", glyph: "#ffffff" },
    dark: { from: "#5b86f0", to: "#e0485a", edge: "#b9ccff", glyph: "#ffffff" },
  },
  // Crypto: violet and teal
  hoenn: {
    frame: "hexagon",
    light: { from: "#7a4de0", to: "#0f9d94", edge: "#3b1f8c", glyph: "#ffffff" },
    dark: { from: "#9b78f5", to: "#22bdb2", edge: "#d3c4ff", glyph: "#ffffff" },
  },
  // Global: silver and indigo
  sinnoh: {
    frame: "diamond",
    light: { from: "#cfd4de", to: "#4b4fb3", edge: "#2c2f78", glyph: "#ffffff" },
    dark: { from: "#e1e5ee", to: "#6a6ee0", edge: "#e8eaff", glyph: "#1f2250" },
  },
  // Creators: gold
  elite: {
    frame: "star",
    light: { from: "#ffd84a", to: "#d99a00", edge: "#8a5d00", glyph: "#5a3b00" },
    dark: { from: "#ffe27a", to: "#e6a400", edge: "#fff0b3", glyph: "#4a3000" },
  },
};

/** Glyphs are drawn in a 24 x 24 box with a 2px round stroke, filled only where `fill` is set. */
export type Glyph = { d: string[]; fill?: boolean };

export const GLYPHS: Record<string, Glyph> = {
  shield: { d: ["M12 3 L19 6 V12 C19 16.5 16 19.5 12 21 C8 19.5 5 16.5 5 12 V6 Z", "M9 12 L11 14 L15 10"] },
  bolt: { d: ["M13 2 L5 14 H11 L10 22 L19 9 H13 Z"], fill: true },
  mountain: { d: ["M2 20 L9 7 L13 14 L16 10 L22 20 Z"], fill: true },
  coin: {
    d: ["M12 3 A9 9 0 1 0 12 21 A9 9 0 1 0 12 3 Z", "M9.5 10 H13.5 A1.5 1.5 0 0 1 13.5 13 H10.5 A1.5 1.5 0 0 0 10.5 16 H14.5", "M12 7.5 V9 M12 16 V17.5"],
  },
  clock: { d: ["M12 3 A9 9 0 1 0 12 21 A9 9 0 1 0 12 3 Z", "M12 7 V12 L15.5 14"] },
  globe: { d: ["M12 3 A9 9 0 1 0 12 21 A9 9 0 1 0 12 3 Z", "M3 12 H21", "M12 3 C8 8 8 16 12 21 C16 16 16 8 12 3"] },
  play: { d: ["M8 5 L19 12 L8 19 Z"], fill: true },
  chart: { d: ["M3 3 V21 H21", "M7 16 L11 11 L14 14 L20 7"] },
  crown: { d: ["M3 18 L2 7 L8 12 L12 5 L16 12 L22 7 L21 18 Z"], fill: true },
  flag: { d: ["M6 3 V21", "M6 4 H18 L15 8 L18 12 H6"] },
  pie: { d: ["M12 3 A9 9 0 1 0 21 12 H12 Z", "M15 3.5 A9 9 0 0 1 20.5 9 H15 Z"] },
  arrowdown: { d: ["M12 4 V20", "M6 14 L12 20 L18 14"] },
  moon: { d: ["M20 14 A8 8 0 1 1 10 4 A6.5 6.5 0 0 0 20 14 Z"], fill: true },
  percent: {
    d: ["M19 5 L5 19", "M7 4.5 A2.5 2.5 0 1 0 7 9.5 A2.5 2.5 0 1 0 7 4.5 Z", "M17 14.5 A2.5 2.5 0 1 0 17 19.5 A2.5 2.5 0 1 0 17 14.5 Z"],
  },
  people: { d: ["M12 4 A3.5 3.5 0 1 0 12 11 A3.5 3.5 0 1 0 12 4 Z", "M4 20 C4 15.5 8 14 12 14 C16 14 20 15.5 20 20"] },
  layers: { d: ["M12 3 L21 8 L12 13 L3 8 Z", "M3 12 L12 17 L21 12", "M3 16 L12 21 L21 16"] },
};

/** Which glyph hints at each badge's condition, and which region's art frames it. */
const ROWS: Record<string, [id: string, glyph: string][]> = {
  kanto: [
    ["boulder", "flag"], ["cascade", "shield"], ["thunder", "bolt"], ["rainbow", "globe"],
    ["soul", "shield"], ["marsh", "clock"], ["volcano", "play"], ["earth", "mountain"],
  ],
  johto: [
    ["zephyr", "flag"], ["hive", "shield"], ["plain", "pie"], ["fog", "arrowdown"],
    ["storm", "globe"], ["mineral", "shield"], ["glacier", "play"], ["rising", "chart"],
  ],
  hoenn: [
    ["stone", "coin"], ["knuckle", "shield"], ["dynamo", "moon"], ["heat", "arrowdown"],
    ["balance", "globe"], ["feather", "shield"], ["mind", "play"], ["rain", "chart"],
  ],
  sinnoh: [
    ["coal", "flag"], ["forest", "shield"], ["cobble", "globe"], ["fen", "percent"],
    ["relic", "clock"], ["mine", "shield"], ["icicle", "clock"], ["beacon", "chart"],
  ],
  elite: [
    ["debut", "flag"], ["trusted", "people"], ["consistent", "chart"], ["craftsman", "layers"], ["champion", "crown"],
  ],
};

export const BADGE_GLYPH: Record<string, string> = {};
export const BADGE_REGION: Record<string, string> = {};
for (const [region, rows] of Object.entries(ROWS)) {
  for (const [id, glyph] of rows) {
    BADGE_GLYPH[id] = glyph;
    BADGE_REGION[id] = region;
  }
}

/** Tab labels, which pair each region with its market. */
export const REGION_LABEL: Record<string, string> = {
  kanto: "Kanto · India",
  johto: "Johto · US",
  hoenn: "Hoenn · Crypto",
  sinnoh: "Sinnoh · Global",
  elite: "Elite Four",
};

export const BADGE_SIZES = { sm: 24, md: 48, lg: 80 } as const;
export type BadgeSize = keyof typeof BADGE_SIZES;
