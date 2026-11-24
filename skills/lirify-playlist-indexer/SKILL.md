---
name: lirify-playlist-indexer
description: >
  Submit public YouTube playlists to Lirify for lyric indexing. Use when a user or
  agent wants a playlist added to a Lirify music library, asks whether a playlist
  URL is indexable, or needs to check the status of an indexing job. Validates
  URLs, calls the bearer-protected Lirify bot API, polls the job, and reports
  machine-readable failures (private, deleted, geo-blocked, rate limited).
version: 1.0.0
license: MIT
---

# Lirify playlist indexer

> **Retired for the cloud deployment.** Lirify is now split: Cloud Run serves a
> read-only index and `python-backend` returns `403`/`UNIMPLEMENTED` for every
> ingestion route. Indexing runs on the laptop via the `local-indexer` gRPC stack
> and its dashboard (`http://localhost:8090`); there is no public HTTP bot API
> unless you run an API yourself with `SERVE_ONLY=false`. The CLI/tool adapters
> below still describe the retired HTTP surface and are kept for reference.

Turn a **public YouTube playlist** into indexed, searchable Lirify tracks.

Lirify is a lyrics-first music index: `python-backend` downloads playlist
metadata, resolves lyrics from a provider chain, keeps tracks that actually have
lyrics (any language), and commits them to MongoDB Atlas + Qdrant
Cloud. This skill is the supported machine entry point — it never touches a
database, only the HTTP bot API.

## When to use this skill

- "Add this playlist to Lirify", "index my playlist", "import this mix".
- "Is this playlist link indexable?" → run `validate`.
- "Did my playlist finish indexing?" → run `status` or `wait`.
- An agent needs a lyric-searchable corpus from a known public playlist.

Do **not** use it for: single videos (no `list=`), private/members-only
playlists, playlists that require sign-in, or bulk crawling of arbitrary
YouTube search results.

## Prerequisites

| Variable | Required | Meaning |
| --- | --- | --- |
| `LIRIFY_BOT_API_URL` | yes | Base URL of `python-backend`, e.g. `https://lirify-api-xxxxx-uc.a.run.app`. Cloud Run scales to zero, so the first call may take ~5 s. |
| `LIRIFY_BOT_API_KEY` | yes | Bearer token matching `BOT_INGEST_API_KEY` on the server. |
| `LIRIFY_BOT_TIMEOUT` | no | Seconds to wait for a job (default `900`). |

Never print the key, and never put it in a URL or a commit.

## Decision procedure

1. **Normalise.** Accept `youtube.com/playlist?list=…`, `music.youtube.com/…`,
   `youtube.com/watch?v=…&list=…`, `youtu.be/…?list=…`, or a bare playlist id
   (`PL…`, `UU…`, `OLAK5uy_…`). Reject other hosts and single-video links.
2. **Validate** (cheap, catches typos before spending quota):
   `GET /api/v1/bot/playlists/validate?playlist_url=…`
3. **Submit**: `POST /api/v1/bot/index-playlist` with
   `Authorization: Bearer $LIRIFY_BOT_API_KEY` and
   `{"playlist_url": "...", "source_bot": "..."}`.
   Send an `Idempotency-Key` header so a retried request cannot enqueue twice.
   Expect `202 Accepted` with `{job_id, status_url, poll_after_seconds}`.
   A repeat submission returns `200` with `"duplicate": true`.
4. **Poll**: `GET /api/v1/bot/jobs/{job_id}` until `status` is `committed`,
   `skipped` or `error`. Respect `poll_after_seconds` (5 s) and stop after
   `LIRIFY_BOT_TIMEOUT`.
5. **Report** the outcome, including `added` and the failure code when relevant.

## Tools provided

Any agent runtime can use these; pick the adapter that matches yours.

| Runtime | Entry point |
| --- | --- |
| CLI / shell / any agent | `scripts/lirify_playlist.py` |
| OpenAI function calling | `schemas/openai_tool.json` |
| Anthropic tool use | `schemas/anthropic_tool.json` |
| MCP (Claude Desktop, Cursor, Zed…) | `mcp/server.py` (stdio JSON-RPC) |
| LangChain | `langchain_tool.py` → `build_lirify_tools()` |

### CLI

```bash
export LIRIFY_BOT_API_URL="https://lirify-api-xxxxx-uc.a.run.app"
export LIRIFY_BOT_API_KEY="…"

# validate only
python3 scripts/lirify_playlist.py validate "https://music.youtube.com/playlist?list=OLAK5uy_xxx"

# submit and wait for the commit
python3 scripts/lirify_playlist.py submit "https://www.youtube.com/playlist?list=PLxxxx" \
  --source-bot my-agent --timeout 600 --json

# fire-and-forget, then poll later
python3 scripts/lirify_playlist.py submit "PLxxxxxxxxxxxx" --no-wait
python3 scripts/lirify_playlist.py wait job-1234567890-abcdef

# agent-owned retry after a YouTube bot check (randomised 15–120 min delay)
python3 scripts/lirify_playlist.py submit "https://www.youtube.com/playlist?list=PLxxxx" \
  --max-retries 2 --jitter-min 900 --jitter-max 7200
```

Exit codes: `0` committed · `2` invalid URL · `3` auth · `4` rate limited ·
`5` permanent job failure · `6` timed out (job may still be running) · `1` other.

### MCP

```json
{
  "mcpServers": {
    "lirify": {
      "command": "python3",
      "args": ["/abs/path/skills/lirify-playlist-indexer/mcp/server.py"],
      "env": {
        "LIRIFY_BOT_API_URL": "https://lirify-api-xxxxx-uc.a.run.app",
        "LIRIFY_BOT_API_KEY": "…"
      }
    }
  }
}
```

### LangChain

```python
from langchain_tool import build_lirify_tools
agent_tools = build_lirify_tools()
```

## API contract

```http
POST /api/v1/bot/index-playlist
Authorization: Bearer $LIRIFY_BOT_API_KEY
Idempotency-Key: my-agent:9f1c…
Content-Type: application/json

{"playlist_url": "https://www.youtube.com/playlist?list=PL…", "source_bot": "my-agent"}
```

```json
202 Accepted
{
  "accepted": true,
  "duplicate": false,
  "job": {"job_id": "job-1794814490370-385f62", "status": "queued", "source": "bot:my-agent"},
  "job_status_url": "/api/v1/bot/jobs/job-1794814490370-385f62",
  "poll_after_seconds": 5
}
```

Job `status` values: `queued` → `indexing` → `matrix_pending` → `committed`
(or `skipped`, `error`). `retry_wait` means a transient failure is backing off.

## Anti-bot strategy: large playlists, agent-owned jitter

YouTube challenges datacenter IPs with a "confirm you're not a bot" page. The
server treats that as **terminal for itself** — it will not silently retry in the
background and burn quota. Recovery is an agent responsibility:

1. **Prefer one large playlist.** A single `yt-dlp --flat-playlist` extraction of a
   25–500 track playlist is one request pattern; ten 5-track submissions are ten
   chances to be challenged. Do not split a large playlist into small jobs.
2. **Do not pass `limit` for large submissions.** `limit` still extracts the whole
   playlist first and then truncates the indexing work, so it saves nothing on the
   scraping side.
3. **Retry only through the API, with random timing.** Poll the job; when the
   failure is `bot_check`, wait a random 15–120 minutes (`--max-retries` /
   `--jitter-min` / `--jitter-max`) and resubmit. A resubmission is a new job with a
   new idempotency key — that is intentional.
4. **Spread retries across playlists.** If several playlists failed, jitter each one
   independently instead of retrying them in a burst.

The server exposes the policy so an agent can schedule it: `failure.retry_mode` is
`agent-jitter`, `failure.retry_window_seconds` is the allowed window, and
`failure.recommended_retry_after_seconds` is a sampled delay.
`next_action.action` is `resubmit` (retryable) or `give_up` (deterministic).

## Failure handling

`GET /api/v1/bot/jobs/{id}` adds a `failure` object with `code`, `retryable`
and `hint`:

| `error_code` | Meaning | What the agent should do |
| --- | --- | --- |
| `private_playlist` | Playlist is private | Ask the owner for a public link. Never retry. |
| `not_found` | Deleted or wrong id | Re-discover the URL. Never retry. |
| `invalid_playlist` | Malformed id (YouTube HTTP 400) | Ask for a fresh URL. Never retry. |
| `unavailable` | YouTube reports it unavailable | Report it; do not loop. |
| `restricted` | Age/members-only | Not indexable without credentials. |
| `geo_blocked` | Geo-restricted for the scraper | Not indexable from this region. |
| `bot_check` | YouTube anti-bot challenge | Retry later or from another egress; do not hammer. |
| `rate_limited` | Server or YouTube 429 | Honour `Retry-After` / `retry_after_seconds`. |
| `network_error` | Transient transport failure | Retry with exponential backoff (max 3). |

Other rules:

- **401/403** → wrong or missing `LIRIFY_BOT_API_KEY`. Stop; do not retry.
- **429** → server-side quota is `BOT_RATE_LIMIT` submissions per
  `BOT_RATE_WINDOW_SECONDS` (default 30/hour) per key. Back off, then retry.
  The limit is disabled when `BOT_RATE_LIMIT=0` (local compose).
- **503 `bot_api_disabled`** → the deployment has no `BOT_INGEST_API_KEY`; the
  operator must set it. Stop.
- **Timed out waiting** → the job is very likely still running (long playlists).
  Poll `status` again later instead of resubmitting.

## Operational notes

- Indexing is **accumulative**: a playlist adds new tracks, it never resets the
  library. Duplicate tracks are skipped and reported as `skipped`.
- Only tracks with non-empty lyrics are committed. Any language is indexable;
  tracks without lyrics are counted in the job's skip statistics, not treated as
  errors.
- `MAX_INDEXED_SONGS` (default 1000) is a capacity guard for the 512 MiB Cloud Run
  container. A batch that would exceed it fails with `Index capacity guard` and
  commits nothing. `-1` disables the guard (local compose with enough RAM).
- Reads are public but rate limited per IP (`PUBLIC_RATE_LIMIT_PER_MINUTE`,
  default 120/min in production, unlimited when `0`). Writes always need the
  bearer token.
- Cloud Run scales to zero: the first request after idle may take a few seconds
  and the client should allow a generous connect timeout.
- Playlists are scraped with `yt-dlp`; very large playlists take minutes. Use
  `limit` for a quick probe (`--limit 5`).

## Security

- The bot key authorises writes to the index. Treat it like a password; rotate it
  in Secret Manager (`lirify-bot-ingest-api-key`) when in doubt.
- Only public YouTube URLs are accepted; the server allowlists hosts and requires
  a `list=` parameter before any scraping happens.
- The client never logs the key and never sends it to any host other than
  `LIRIFY_BOT_API_URL`.
