import { text } from "./locale";

export function fmtTime(seconds: number | null | undefined): string {
  if (!seconds || !Number.isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (!seconds) return "0 min";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `${hours} hr ${rest} min`;
}

export function fmtCount(value: number): string {
  return new Intl.NumberFormat(text("es-EC", "en-US"), { notation: value > 9999 ? "compact" : "standard" }).format(
    value || 0,
  );
}

export function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return text("Buenos días", "Good morning");
  if (hour < 18) return text("Buenas tardes", "Good afternoon");
  return text("Buenas noches", "Good evening");
}

export function escapeHtml(text: unknown): string {
  return String(text ?? "").replace(/[&<>"']/g, (char) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] as string,
  );
}

export function highlight(text: string, query: string): string {
  const words = query
    .split(/\s+/)
    .map((word) => word.trim())
    .filter((word) => word.length > 1)
    .map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const safe = escapeHtml(text);
  if (!words.length) return safe;
  const pattern = new RegExp(`(${words.join("|")})`, "gi");
  return safe.replace(pattern, "<mark>$1</mark>");
}

export function debounce<T extends (...args: any[]) => void>(fn: T, wait = 220): T {
  let timer: number | undefined;
  return ((...args: Parameters<T>) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), wait);
  }) as T;
}

export function throttle<T extends (...args: any[]) => void>(fn: T, wait = 500): T {
  let last = 0;
  let timer: number | undefined;
  let lastArgs: Parameters<T> | null = null;
  return ((...args: Parameters<T>) => {
    const now = Date.now();
    const remaining = wait - (now - last);
    lastArgs = args;
    if (remaining <= 0) {
      window.clearTimeout(timer);
      timer = undefined;
      last = now;
      fn(...args);
    } else if (!timer) {
      timer = window.setTimeout(() => {
        timer = undefined;
        last = Date.now();
        if (lastArgs) fn(...lastArgs);
      }, remaining);
    }
  }) as T;
}

export function hashHue(seed: string): number {
  let hash = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    hash ^= seed.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return Math.abs(hash) % 360;
}

export function seededBars(seed: string, count = 64): number[] {
  let hash = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    hash ^= seed.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  const bars: number[] = [];
  for (let i = 0; i < count; i++) {
    hash ^= hash << 13;
    hash ^= hash >>> 17;
    hash ^= hash << 5;
    const value = Math.abs(hash % 1000) / 1000;
    const envelope = 0.45 + 0.55 * Math.sin((i / count) * Math.PI);
    bars.push(Math.max(0.16, Math.min(1, (0.3 + value * 0.85) * envelope)));
  }
  return bars;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function splitArtists(artist: string): string[] {
  return (artist || "")
    .split(/\s*(?:,|&|feat\.?|ft\.?|x)\s*/i)
    .map((part) => part.trim())
    .filter(Boolean);
}
