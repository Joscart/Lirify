// Adaptive colour theming: turn the playing cover into an accent the whole shell
// reads from. The picking is deliberately cheap (32×32 buckets); the colour maths
// matches the Limusic approach — pull the winning hue to a brightness that reads
// on a dark surface and keep as much saturation as that allows.

import { hashHue } from "./format";

const SIZE = 32;
const cache = new Map<string, string | null>();

export interface Hsv {
  h: number;
  s: number;
  v: number;
}

const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

function hexToRgb(hex: string): [number, number, number] | null {
  const match = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!match) return null;
  const value = match[1].length === 3 ? [...match[1]].map((c) => c + c).join("") : match[1];
  return [0, 2, 4].map((i) => parseInt(value.slice(i, i + 2), 16) / 255) as [
    number,
    number,
    number,
  ];
}

function rgbToHex(r: number, g: number, b: number): string {
  return (
    "#" +
    [r, g, b]
      .map((channel) => Math.max(0, Math.min(255, Math.round(channel))).toString(16).padStart(2, "0"))
      .join("")
  );
}

export function hexToHsv(hex: string): Hsv | null {
  const rgb = hexToRgb(hex);
  if (!rgb) return null;
  const [r, g, b] = rgb;
  const max = Math.max(r, g, b);
  const delta = max - Math.min(r, g, b);
  let h = 0;
  if (delta) {
    if (max === r) h = ((g - b) / delta) % 6;
    else if (max === g) h = (b - r) / delta + 2;
    else h = (r - g) / delta + 4;
    h = (h * 60 + 360) % 360;
  }
  return { h, s: max ? delta / max : 0, v: max };
}

export function hsvToHex({ h, s, v }: Hsv): string {
  s = clamp01(s);
  v = clamp01(v);
  const channel = (n: number) => {
    const k = (n + h / 60) % 6;
    return 255 * v * (1 - s * Math.max(0, Math.min(k, 4 - k, 1)));
  };
  return rgbToHex(channel(5), channel(3), channel(1));
}

export function brightness(hex: string): number {
  const rgb = hexToRgb(hex);
  if (!rgb) return 0;
  const [r, g, b] = rgb;
  return Math.sqrt(0.299 * r * r + 0.587 * g * g + 0.114 * b * b);
}

/** Winning colour of an RGBA buffer, ignoring greyscale covers. */
function pickAccent(data: Uint8ClampedArray): string | null {
  const buckets = new Map<number, { n: number; r: number; g: number; b: number; score: number }>();
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 128) continue;
    const r = data[i];
    const g = data[i + 1];
    const b = data[i + 2];
    const max = Math.max(r, g, b) / 255;
    const min = Math.min(r, g, b) / 255;
    const saturation = max ? (max - min) / max : 0;
    const score = saturation * (1 - Math.abs(max - 0.65));
    const key = ((r >> 5) << 6) | ((g >> 5) << 3) | (b >> 5);
    const current = buckets.get(key) ?? { n: 0, r: 0, g: 0, b: 0, score: 0 };
    buckets.set(key, {
      n: current.n + 1,
      r: current.r + r,
      g: current.g + g,
      b: current.b + b,
      score: current.score + score,
    });
  }
  let best: { n: number; r: number; g: number; b: number; score: number } | null = null;
  for (const bucket of buckets.values()) {
    if (!best || bucket.score > best.score) best = bucket;
  }
  if (!best) return null;
  const hex = rgbToHex(best.r / best.n, best.g / best.n, best.b / best.n);
  const hsv = hexToHsv(hex);
  if (!hsv || hsv.s < 0.14) return null;
  return hex;
}

/** Pull a cover colour to a brightness that works as an accent on dark surfaces. */
export function toAccent(hex: string, target = 0.66): string {
  const hsv = hexToHsv(hex);
  if (!hsv) return hex;
  const at = (s: number, v: number) => brightness(hsvToHex({ h: hsv.h, s, v }));
  let s = Math.min(0.82, Math.max(0.48, hsv.s));
  if (at(s, 1) < target) {
    let lo = 0;
    let hi = s;
    for (let i = 0; i < 12; i++) {
      const mid = (lo + hi) / 2;
      if (at(mid, 1) < target) hi = mid;
      else lo = mid;
    }
    s = lo;
  }
  const full = at(s, 1);
  return hsvToHex({ h: hsv.h, s, v: full ? Math.min(1, target / full) : 1 });
}

function withHue(hex: string, delta: number, saturationScale = 1, valueScale = 1): string {
  const hsv = hexToHsv(hex);
  if (!hsv) return hex;
  return hsvToHex({
    h: (hsv.h + delta + 360) % 360,
    s: clamp01(hsv.s * saturationScale),
    v: clamp01(hsv.v * valueScale),
  });
}

export function fallbackAccent(seed: string): string {
  return toAccent(hsvToHex({ h: hashHue(seed || "lirify"), s: 0.62, v: 0.86 }));
}

async function readCover(url: string): Promise<string | null> {
  return new Promise((resolve) => {
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.decoding = "async";
    image.onload = () => {
      try {
        const canvas = document.createElement("canvas");
        canvas.width = SIZE;
        canvas.height = SIZE;
        const context = canvas.getContext("2d", { willReadFrequently: true });
        if (!context) return resolve(null);
        context.drawImage(image, 0, 0, SIZE, SIZE);
        resolve(pickAccent(context.getImageData(0, 0, SIZE, SIZE).data));
      } catch {
        resolve(null);
      }
    };
    image.onerror = () => resolve(null);
    image.src = url;
  });
}

export async function accentForCover(url: string, seed: string): Promise<string> {
  if (!url) return fallbackAccent(seed);
  if (cache.has(url)) {
    return cache.get(url) || fallbackAccent(seed);
  }
  const picked = await readCover(url);
  const accent = picked ? toAccent(picked) : null;
  if (cache.size > 240) cache.clear();
  // Cache the *adjusted* accent: the raw cover colour is too dark or too pale
  // to be read as a UI accent, and a second card would otherwise get the raw one.
  cache.set(url, accent);
  return accent || fallbackAccent(seed);
}

let currentAccent = "";

export function applyAccent(accent: string): void {
  if (!accent) return;
  currentAccent = accent;
  const root = document.documentElement;
  const hsv = hexToHsv(accent);
  root.style.setProperty("--accent", accent);
  root.style.setProperty("--accent-strong", withHue(accent, 0, 1, 1.12));
  root.style.setProperty("--accent-deep", withHue(accent, -8, 1, 0.72));
  root.style.setProperty("--accent-2", withHue(accent, 46, 0.95, 1.02));
  root.style.setProperty("--art-1", accent);
  root.style.setProperty("--art-2", withHue(accent, -38, 0.9, 0.82));
  if (hsv) root.style.setProperty("--art-h", String(Math.round(hsv.h)));
  root.dataset.accent = accent;
}

export function currentArtAccent(): string {
  return currentAccent;
}

export function brandAccent(): string {
  return "#b48bff";
}

export function resetAccent(): void {
  applyAccent(brandAccent());
}

export async function applyTrackAccent(
  track: { video_id: string; thumb?: string; art?: string } | null,
  enabled: boolean,
): Promise<void> {
  if (!enabled || !track) {
    resetAccent();
    return;
  }
  const seed = track.video_id || track.thumb || "lirify";
  // Read the 480×360 thumbnail: every video has one, while maxresdefault is a
  // 404 for plenty of them. The colour is identical either way.
  const url = track.thumb || track.art || "";
  const accent = url ? await accentForCover(url, seed) : fallbackAccent(seed);
  applyAccent(accent);
}
