// Makes an official brand colour safe to paint on our surfaces.
//
// Brand hexes are chosen against the brand's own background, not ours, so a
// meaningful number of them are illegible here: Apple is #000000 and Anthropic
// #191919, both invisible on the dark theme's #141416 card. Simply not tinting
// those would drop brand identity for some of the most recognisable companies in
// the catalog, so instead we lift lightness by the minimum needed to clear a
// contrast floor and keep the hue.
//
// The floor is 3:1 — WCAG 2.2 SC 1.4.11 (non-text contrast), which is the
// correct bar for a graphical mark. 4.5:1 is the body-text bar and would distort
// hues far past recognition for no accessibility gain.

/** Card surface each theme actually paints these marks on (`--app-surface-raised`). */
const SURFACE = { light: "#ffffff", dark: "#141416" } as const;

export type Theme = keyof typeof SURFACE;

const MIN_CONTRAST = 3;

export function parseHex(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{6}|[0-9a-f]{3})$/i.exec(hex.trim());
  if (!m) return null;
  const h = m[1].length === 3 ? [...m[1]].map((c) => c + c).join("") : m[1];
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

const toHex = (rgb: [number, number, number]) =>
  "#" + rgb.map((c) => Math.round(Math.max(0, Math.min(255, c))).toString(16).padStart(2, "0")).join("");

/** WCAG relative luminance. Channels are linearised before weighting — skipping
 *  that step is the classic bug that makes mid-tones read as far too light. */
export function luminance(rgb: [number, number, number]): number {
  const [r, g, b] = rgb.map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
  const [ra, rb] = [parseHex(a), parseHex(b)];
  if (!ra || !rb) return 1;
  const [la, lb] = [luminance(ra), luminance(rb)];
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

function toHsl([r, g, b]: [number, number, number]): [number, number, number] {
  const [rn, gn, bn] = [r / 255, g / 255, b / 255];
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  const d = max - min;
  if (d === 0) return [0, 0, l];
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  if (max === rn) h = ((gn - bn) / d + (gn < bn ? 6 : 0)) / 6;
  else if (max === gn) h = ((bn - rn) / d + 2) / 6;
  else h = ((rn - gn) / d + 4) / 6;
  return [h, s, l];
}

/** HSL (h in degrees, s/l in 0..1) -> '#rrggbb'. Exported because callers that
 *  synthesise a colour must hand brandInk a hex — it parses nothing else, and a
 *  raw `hsl()` string silently degrades to currentColor. */
export function hslToHex(hDeg: number, s: number, l: number): string {
  return toHex(toRgb([(((hDeg % 360) + 360) % 360) / 360, s, l]));
}

function toRgb([h, s, l]: [number, number, number]): [number, number, number] {
  if (s === 0) return [l * 255, l * 255, l * 255];
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const channel = (t: number) => {
    let x = t;
    if (x < 0) x += 1;
    if (x > 1) x -= 1;
    if (x < 1 / 6) return p + (q - p) * 6 * x;
    if (x < 1 / 2) return q;
    if (x < 2 / 3) return p + (q - p) * (2 / 3 - x) * 6;
    return p;
  };
  return [channel(h + 1 / 3) * 255, channel(h) * 255, channel(h - 1 / 3) * 255];
}

/**
 * Returns `hex` adjusted to clear MIN_CONTRAST against `theme`'s card surface,
 * preserving hue and saturation. Already-legible colours are returned untouched,
 * so the common case is exact brand fidelity.
 *
 * Walks lightness away from the surface in small steps rather than jumping to a
 * computed target: contrast is non-linear in HSL lightness, so stepping is what
 * keeps the shift minimal. Falls back to plain white/black only for a hue that
 * cannot reach the floor at any lightness (fully saturated yellow on white).
 */
export function brandInk(hex: string, theme: Theme): string {
  const rgb = parseHex(hex);
  if (!rgb) return "currentColor";
  const surface = SURFACE[theme];
  if (contrast(hex, surface) >= MIN_CONTRAST) return toHex(rgb);

  const [h, s] = toHsl(rgb);
  const dir = theme === "dark" ? 1 : -1;
  let [, , l] = toHsl(rgb);
  for (let i = 0; i < 100; i += 1) {
    l += dir * 0.01;
    if (l < 0 || l > 1) break;
    const candidate = toHex(toRgb([h, s, l]));
    if (contrast(candidate, surface) >= MIN_CONTRAST) return candidate;
  }
  return theme === "dark" ? "#ffffff" : "#000000";
}
