export type ViewName =
  | "home"
  | "search"
  | "library"
  | "artist"
  | "playlist"
  | "videos";

export interface Track {
  id: string;
  video_id: string;
  kind: "track" | "video" | string;
  title: string;
  youtube_title?: string;
  artist: string;
  artist_id: string;
  language: string;
  language_name: string;
  lyrics_source?: string;
  thumb: string;
  art: string;
  poster?: string;
  duration: number;
  duration_estimated?: boolean;
  synced_lyrics: boolean;
  lines?: number;
  match?: number;
  score?: number;
  snippet?: string;
  youtube_url?: string;
}

export interface Artist {
  id: string;
  kind: "artist";
  name: string;
  title: string;
  count: number;
  languages: Record<string, number>;
  language: string;
  language_name: string;
  cover: string;
  art: string;
  top_track?: Track | null;
  score: number;
}

export interface Playlist {
  id: string;
  kind: "playlist";
  title: string;
  subtitle: string;
  tag: string;
  count: number;
  duration: number;
  synced?: number;
  cover: string;
  covers: string[];
  track_ids: string[];
}

export interface Shelf {
  id: string;
  title: string;
  subtitle: string;
  kind: "tracks" | "artists" | "playlists" | "videos";
  items: Array<Track | Artist | Playlist>;
}

export interface LanguageChip {
  code: string;
  name: string;
  count: number;
}

export interface Bootstrap {
  library: {
    songs: number;
    artists: number;
    playlists: number;
    languages: number;
    videos: number;
    terms: number;
    tokens: number;
    synced: number;
    weights: Record<string, number>;
    generated_at: number;
  };
  hero: (Track & { rank: number; blurb: string }) | null;
  languages: LanguageChip[];
  shelves: Shelf[];
  artists: Artist[];
  playlists: Playlist[];
  top_tracks: Track[];
  capabilities: { streaming: boolean; video: boolean; synced_lyrics: boolean; resolver: string };
}

export interface LyricWord {
  t: number;
  text: string;
}

export interface LyricLine {
  t: number | null;
  text: string;
  words?: LyricWord[];
}

export interface LyricsPayload {
  video_id: string;
  title: string;
  artist: string;
  source: string;
  language: string;
  synced: boolean;
  offset: number;
  duration: number;
  duration_estimated?: boolean;
  lines: LyricLine[];
}

export interface SearchPayload {
  query: string;
  top: Track | Artist | null;
  tracks: Track[];
  artists: Artist[];
  snippet: string;
  scanned: number;
}

export interface ArtistPayload {
  artist: Artist;
  tracks: Track[];
  similar: Artist[];
}

export interface PlaylistPayload {
  playlist: Playlist;
  total: number;
  offset?: number;
  tracks: Track[];
}

export interface SessionPayload {
  active: boolean;
  video_id?: string;
  position?: number;
  duration?: number;
  state?: "playing" | "paused";
  synced?: boolean;
  line_index?: number | null;
  line?: LyricLine | null;
  next_line?: LyricLine | null;
  lines_total?: number;
  server_time?: number;
  track?: Track;
}

export interface StreamPayload {
  video_id: string;
  kind: "audio" | "video";
  proxy_url: string;
  expires_at: number;
  duration: number;
  resolver: string;
  available?: boolean;
  error?: string;
}
