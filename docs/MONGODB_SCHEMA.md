# MongoDB schema

`local-indexer` is the only writer of index state: it publishes songs and bumps
`index_stats.revision` through `core.publicar()`. The Cloud Run `python-backend`
is read-only and refuses every index write at the `store.py` boundary (resolved
media durations remain an allowed player-metadata write). Documents are
Mongo-native (`_id`) with camelCase fields, `schemaVersion` and
`createdAt`/`updatedAt` timestamps.

`services/api/app/store.py` creates the collections, `$jsonSchema` validators
(`validationLevel: moderate`, `validationAction: warn`) and indexes on boot, so a
fresh Atlas M0 cluster needs no manual setup.

`jobs`, `stashes`, `lyrics_cache`, `failed_songs` and the two `bot_*` collections
are legacy: the standalone indexer keeps jobs in memory and has no retry ledger.
They are listed below because the schema layer still defines them.

```js
// docs/mongo/lirify.models.js — reference Mongoose models (not used at runtime)
import mongoose from "mongoose";

const opts = { timestamps: true, versionKey: false };

const Song = mongoose.model("Song", new mongoose.Schema({
  videoId:       { type: String, required: true, unique: true, match: /^[A-Za-z0-9_-]{11}$/ },
  title:         { type: String, required: true },   // normalised track title
  youtubeTitle:  { type: String, default: "" },
  artist:        { type: String, default: "" },
  language:      { type: String, required: true },   // primary label; any language indexed
  languages:     { type: [String], default: [] },    // every language detected line by line
  lyrics:        { type: String, required: true },
  backend:       { type: String, default: "" },      // lyrics provider that resolved it
  duration:      { type: Number, default: null },
  schemaVersion: { type: Number, default: 1 },
}, opts));

const LyricsCache = mongoose.model("LyricsCache", new mongoose.Schema({
  videoId:      { type: String, required: true, unique: true },
  title:        { type: String, default: "" },
  youtubeTitle: { type: String, default: "" },
  artist:       { type: String, default: "" },
  language:     { type: String, default: "" },
  lyrics:       { type: String, required: true },
  backend:      { type: String, default: "" },
  cachedAt:     { type: Date, default: Date.now },
  schemaVersion:{ type: Number, default: 1 },
}, { versionKey: false }));

const FailedSong = mongoose.model("FailedSong", new mongoose.Schema({
  videoId:  { type: String, required: true, unique: true },
  title:    { type: String, default: "" },
  artist:   { type: String, default: "" },
  duration: { type: Number, default: null },
  attempts: { type: Number, default: 0 },
  reason:   { type: String, default: "no lyrics" },
  lastTry:  { type: Date, default: Date.now },
  schemaVersion: { type: Number, default: 1 },
}, { versionKey: false }));

const Job = mongoose.model("Job", new mongoose.Schema({
  jobId:   { type: String, required: true, unique: true },
  action:  { type: String, enum: ["queue", "index", "extract", "retry_failed"], default: "queue" },
  url:     { type: String, default: "" },
  limit:   { type: Number, default: null },
  status:  { type: String, required: true },  // queued|indexing|matrix_pending|committed|skipped|error|retry_wait
  stage:   { type: String, default: "" },
  attempts:{ type: Number, default: 0 },
  error:   { type: String, default: null },
  errorCode:{ type: String, default: null },  // bot_api.classify_playlist_error
  retryMode:{ type: String, default: null },  // never | agent-jitter
  added:   { type: Number, default: 0 },
  source:  { type: String, default: "manual" }, // go-webui | bot:<name> | manual
  batchId: { type: String, default: null },
  lastEvent: { type: String, default: null },
  schemaVersion: { type: Number, default: 1 },
}, opts));

const Stash = mongoose.model("Stash", new mongoose.Schema({
  jobId: { type: String, required: true, unique: true },
  songs: { type: [mongoose.Schema.Types.Mixed], required: true },
  stash: { type: mongoose.Schema.Types.Mixed, required: true }, // {index, terms, tokens, docs}
  createdAt: { type: Date, default: Date.now },
  schemaVersion: { type: Number, default: 1 },
}, { versionKey: false }));

const IndexStats = mongoose.model("IndexStats", new mongoose.Schema({
  _id:   { type: String, default: "global" },
  build: { type: mongoose.Schema.Types.Mixed, required: true },
  updatedAt: { type: Date, default: Date.now },
  schemaVersion: { type: Number, default: 1 },
}, { versionKey: false }));

const MediaDuration = mongoose.model("MediaDuration", new mongoose.Schema({
  videoId:  { type: String, required: true, unique: true },
  duration: { type: Number, required: true },
  updatedAt:{ type: Date, default: Date.now },
}, { versionKey: false }));

const BotRateLimit = mongoose.model("BotRateLimit", new mongoose.Schema({
  _id:     { type: String, required: true },  // "bot:<sha256(key)[:32]>"
  count:   { type: Number, default: 0 },
  resetAt: { type: Date, required: true },    // TTL index, expireAfterSeconds = 0
}, { versionKey: false }));

const BotIdempotency = mongoose.model("BotIdempotency", new mongoose.Schema({
  _id:     { type: String, required: true },  // client Idempotency-Key or bot:sha(url)
  jobId:   { type: String, required: true },
  createdAt: { type: Date, default: Date.now }, // TTL index, 7 days
}, { versionKey: false }));
```

## Collection and index summary

| Collection | Unique index | Other indexes | TTL |
| --- | --- | --- | --- |
| `songs` | `videoId` | `language` | — |
| `lyrics_cache` | `videoId` | — | — |
| `failed_songs` | `videoId` | `lastTry` | — |
| `jobs` | `jobId` | `status`, `createdAt` | — |
| `stashes` | `jobId` | — | — |
| `index_stats` | `_id = "global"` | — | — |
| `media_durations` | `videoId` | — | — |
| `bot_rate_limits` | `_id` | — | `resetAt` + 1 h |
| `bot_idempotency` | `_id` | `createdAt` | `createdAt` + 7 d |

## Size planning (M0 = 512 MB)

A track with a 4 KB lyric blob is ≈ 5 KB in BSON; 1000 tracks ≈ 5 MB. The
`lyrics_cache` mirrors successful lookups (another ≈ 7.5 MB) and `stashes` are
transient. An M0 cluster is comfortably large for several thousand tracks.

## Index statistics document

`index_stats` stores the last computed `build` object:

```json
{
  "songs_indexed": 412,
  "video_ids": 412,
  "vocabulary_size": 18234,
  "inverted_terms": 18234,
  "lyrics_tokens": 138294,
  "languages": {"en": 377, "es": 35},
  "detected_languages": {"en": 390, "es": 48, "fr": 6},
  "backends": {"limusic": 260, "boidu": 152},
  "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
  "embedding_dim": 1024,
  "embedding_provider": "sentence-transformers"
}
```

It is rewritten on every publish together with `revision`. Only counts and
embedding metadata are stored: no matrices ever reach Atlas or Qdrant, and the
cloud replica reads this document for `/stats`.
