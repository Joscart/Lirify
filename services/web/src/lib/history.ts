/**
 * Browser-owned listening history.
 *
 * Lirify keeps no server-side user profile: this module is the entire "user" of
 * the recommendation system. History and recommendation seeds live in
 * localStorage, so a Cloud Run cold start cannot lose them and a different device
 * simply starts with its own empty history.
 *
 * The onboarding gate uses `hasOnboarded()`: a first-time browser must run at
 * least one search before the home view fetches personalised recommendations.
 */

import type { Track } from "./types";

const HISTORY_KEY = "lirify.history.v2";
const SEARCH_KEY = "lirify.searches.v2";
const HISTORY_LIMIT = 60;
const SEARCH_LIMIT = 40;

export interface HistoryEntry {
  video_id: string;
  title: string;
  artist: string;
  art?: string;
  played_at: number;
  plays: number;
}

export interface SearchEntry {
  query: string;
  ts: number;
}

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode or quota: history is best effort, never fatal */
  }
}

export function getHistory(): HistoryEntry[] {
  return read<HistoryEntry[]>(HISTORY_KEY, []);
}

export function getSearches(): SearchEntry[] {
  return read<SearchEntry[]>(SEARCH_KEY, []);
}

export function recordPlay(track: Track): void {
  if (!track?.video_id) return;
  const history = getHistory();
  const existing = history.find((entry) => entry.video_id === track.video_id);
  const rest = history.filter((entry) => entry.video_id !== track.video_id);
  rest.unshift({
    video_id: track.video_id,
    title: track.title,
    artist: track.artist,
    art: track.art,
    played_at: Date.now(),
    plays: (existing?.plays || 0) + 1,
  });
  write(HISTORY_KEY, rest.slice(0, HISTORY_LIMIT));
}

export function recordSearch(query: string): void {
  const trimmed = (query || "").trim();
  if (trimmed.length < 2) return;
  const searches = getSearches().filter(
    (entry) => entry.query.toLowerCase() !== trimmed.toLowerCase(),
  );
  searches.unshift({ query: trimmed, ts: Date.now() });
  write(SEARCH_KEY, searches.slice(0, SEARCH_LIMIT));
}

/** Newest distinct video ids, used as recommendation seeds. */
export function seeds(limit = 5): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const entry of getHistory()) {
    if (seen.has(entry.video_id)) continue;
    seen.add(entry.video_id);
    out.push(entry.video_id);
    if (out.length >= limit) break;
  }
  return out;
}

export function playCount(videoId: string): number {
  const entry = getHistory().find((row) => row.video_id === videoId);
  return entry?.plays || 0;
}

/** A browser is onboarded once it has searched at least once. */
export function hasOnboarded(): boolean {
  return getSearches().length > 0;
}

export function clearHistory(): void {
  try {
    localStorage.removeItem(HISTORY_KEY);
    localStorage.removeItem(SEARCH_KEY);
  } catch {
    /* ignore */
  }
}
