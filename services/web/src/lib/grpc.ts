/**
 * Server-side gRPC client for python-backend.
 *
 * This module must never be imported from a browser component: it is only used by
 * Astro SSR endpoints (`src/pages/api/player/[...path].ts`). The browser talks to
 * Astro's own origin, Astro talks gRPC over TLS (443 on Cloud Run), and only
 * python-backend ever holds MongoDB/Qdrant credentials.
 */

import { existsSync } from "node:fs";
import path from "node:path";
import * as grpc from "@grpc/grpc-js";
import * as protoLoader from "@grpc/proto-loader";

// Generated from proto/lirify.proto by scripts/gen_proto.sh. CI fails when these
// drift, so the TypeScript contract cannot silently go stale.
import type { ProtoGrpcType } from "../generated/lirify";
import type { GetLyricsResponse__Output } from "../generated/lirify/v1/GetLyricsResponse";
import type { GetTrackResponse__Output } from "../generated/lirify/v1/GetTrackResponse";
import type { RecommendResponse__Output } from "../generated/lirify/v1/RecommendResponse";
import type { SearchResponse__Output } from "../generated/lirify/v1/SearchResponse";
import type { Track__Output } from "../generated/lirify/v1/Track";
import type { TrackSummary__Output } from "../generated/lirify/v1/TrackSummary";
import type { Track } from "./types";

// Resolution order keeps `npm run dev` inside services/web and the Docker image
// (PROTO_PATH=/app/proto/lirify.proto) working with the same code.
const PROTO_PATH = (() => {
  const candidates = [
    process.env.PROTO_PATH,
    path.resolve(process.cwd(), "proto/lirify.proto"),
    path.resolve(process.cwd(), "../../proto/lirify.proto"),
    path.resolve(process.cwd(), "../proto/lirify.proto"),
  ].filter((value): value is string => Boolean(value));
  return candidates.find((candidate) => existsSync(candidate)) || candidates[0];
})();

const LANGUAGE_NAMES: Record<string, string> = {
  en: "English",
  es: "Español",
  pt: "Português",
  fr: "Français",
  de: "Deutsch",
  it: "Italiano",
  ja: "日本語",
  ko: "한국어",
  unknown: "Unknown",
};

type TrackSummary = TrackSummary__Output;
type ProtoTrack = Track__Output;

interface ProtoClient extends grpc.Client {
  search(
    request: { query: string; limit: number },
    callback: (error: grpc.ServiceError | null, response: any) => void,
  ): grpc.ClientUnaryCall;
  recommend(
    request: { videoId: string; limit: number; seedVideoIds: string[] },
    callback: (error: grpc.ServiceError | null, response: any) => void,
  ): grpc.ClientUnaryCall;
  getTrack(
    request: { videoId: string; includeLyrics: boolean },
    callback: (error: grpc.ServiceError | null, response: any) => void,
  ): grpc.ClientUnaryCall;
  getLyrics(
    request: { videoId: string },
    callback: (error: grpc.ServiceError | null, response: any) => void,
  ): grpc.ClientUnaryCall;
  listTracks(
    request: { offset: number; limit: number; language: string },
    callback: (error: grpc.ServiceError | null, response: any) => void,
  ): grpc.ClientUnaryCall;
}

let client: ProtoClient | null = null;

function target(): string {
  return process.env.GRPC_TARGET || "127.0.0.1:50051";
}

function credentials(): grpc.ChannelCredentials {
  if (process.env.GRPC_INSECURE === "true") return grpc.credentials.createInsecure();
  return grpc.credentials.createSsl();
}

export function getClient(): ProtoClient {
  if (client) return client;
  const definition = protoLoader.loadSync(PROTO_PATH, {
    keepCase: false,
    longs: Number,
    enums: String,
    defaults: true,
    oneofs: true,
  });
  const loaded = grpc.loadPackageDefinition(definition) as unknown as ProtoGrpcType;
  const Service = loaded.lirify?.v1?.LirifyService as unknown as
    | (new (
        address: string,
        creds: grpc.ChannelCredentials,
        options?: grpc.ChannelOptions,
      ) => ProtoClient)
    | undefined;
  if (!Service) {
    throw new Error(`Could not load lirify.v1.LirifyService from ${PROTO_PATH}`);
  }
  const options: grpc.ChannelOptions = {
    "grpc.max_receive_message_length": 16 * 1024 * 1024,
    "grpc.keepalive_time_ms": 60_000,
  };
  if (process.env.GRPC_AUTHORITY) {
    options["grpc.ssl_target_name_override"] = process.env.GRPC_AUTHORITY;
    options["grpc.default_authority"] = process.env.GRPC_AUTHORITY;
  }
  client = new Service(target(), credentials(), options);
  return client;
}

function call<T>(method: keyof ProtoClient, request: unknown, timeoutMs = 12_000): Promise<T> {
  const stub = getClient();
  return new Promise<T>((resolve, reject) => {
    const deadline = new Date(Date.now() + timeoutMs);
    const metadata = new grpc.Metadata();
    metadata.set("x-lirify-client", "astro-webui");
    (stub[method] as Function).call(
      stub,
      request,
      metadata,
      { deadline },
      (error: grpc.ServiceError | null, response: T) => {
        if (error) reject(error);
        else resolve(response);
      },
    );
  });
}

// ---------------------------------------------------------------------------
// Shape adapters: python-backend speaks protobuf, the player speaks Track JSON
// ---------------------------------------------------------------------------

function thumb(videoId: string, size: "hq" | "maxres" = "hq"): string {
  return `https://i.ytimg.com/vi/${videoId}/${size}default.jpg`;
}

function slugify(text: string): string {
  return (
    (text || "unknown")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "unknown"
  );
}

function toTrack(row: TrackSummary | ProtoTrack): Track {
  const language = row.language || "unknown";
  const videoId = row.videoId || "";
  const score = "score" in row ? Number(row.score) || 0 : 0;
  const synced = "synced" in row ? Boolean(row.synced) : false;
  return {
    id: videoId,
    video_id: videoId,
    kind: "track",
    title: row.title || videoId,
    artist: row.artist || "Unknown artist",
    artist_id: slugify(row.artist),
    language,
    language_name: LANGUAGE_NAMES[language] || language,
    thumb: row.thumb || thumb(videoId),
    art: thumb(videoId, "maxres"),
    duration: Math.round(Number(row.duration) || 0),
    duration_estimated: !(Number(row.duration) > 0),
    synced_lyrics: synced,
    score,
    youtube_url: videoId ? `https://www.youtube.com/watch?v=${videoId}` : undefined,
  };
}

export interface SearchPayload {
  query: string;
  top: Track | null;
  tracks: Track[];
  artists: never[];
  snippet: string;
  scanned: number;
}

export async function search(query: string, limit = 24): Promise<SearchPayload> {
  const trimmed = (query || "").trim();
  if (!trimmed) {
    return { query: trimmed, top: null, tracks: [], artists: [], snippet: "", scanned: 0 };
  }
  const response = await call<SearchResponse__Output>(
    "search",
    { query: trimmed, limit: Math.min(Math.max(limit, 1), 60) },
  );
  const tracks = (response.results || []).map(toTrack);
  return {
    query: response.query || trimmed,
    top: tracks[0] || null,
    tracks,
    artists: [],
    snippet: "",
    scanned: tracks.length,
  };
}

export interface RadioPayload {
  seed: Track;
  score_weights: Record<string, number>;
  recommendations: Array<Track & { match: number }>;
  engine: string;
}

export async function recommend(
  videoId: string,
  seedVideoIds: string[] = [],
  limit = 16,
): Promise<RadioPayload> {
  const seeds = Array.from(new Set([videoId, ...seedVideoIds].filter(Boolean))).slice(0, 5);
  const [seedResponse, recResponse] = await Promise.all([
    call<GetTrackResponse__Output>("getTrack", { videoId, includeLyrics: false }),
    call<RecommendResponse__Output>("recommend", {
      videoId,
      limit: Math.min(Math.max(limit, 1), 50),
      seedVideoIds: seeds,
    }),
  ]);
  return {
    seed: toTrack(seedResponse.track),
    score_weights: {},
    engine: recResponse.engine || "unknown",
    recommendations: (recResponse.recommendations || []).map((row) => ({
      ...toTrack(row),
      match: Math.round(Math.min(1, Math.max(0, Number(row.score) || 0)) * 100),
    })),
  };
}

export interface LyricsPayload {
  video_id: string;
  synced: boolean;
  language: string;
  lines: Array<{ t: number; text: string }>;
  raw: string;
}

export async function lyrics(videoId: string): Promise<LyricsPayload> {
  const response = await call<GetLyricsResponse__Output>("getLyrics", { videoId });
  return {
    video_id: response.videoId || videoId,
    synced: Boolean(response.synced),
    language: response.language || "unknown",
    lines: (response.lines || []).map((line) => ({
      t: Number(line.timeMs) / 1000,
      text: line.text || "",
    })),
    raw: response.raw || "",
  };
}

export async function track(videoId: string): Promise<Track | null> {
  try {
    const response = await call<GetTrackResponse__Output>("getTrack", {
      videoId,
      includeLyrics: false,
    });
    return response.track ? toTrack(response.track) : null;
  } catch (error) {
    if ((error as grpc.ServiceError).code === grpc.status.NOT_FOUND) return null;
    throw error;
  }
}

export function backendTarget(): string {
  return target();
}

export function backendSecure(): boolean {
  return process.env.GRPC_INSECURE !== "true";
}
