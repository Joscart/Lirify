"""Bot ingestion API (HTTP/JSON) for external AI agents.

`POST /api/v1/bot/index-playlist` is the only write path a machine client needs:

    Authorization: Bearer $LIRIFY_BOT_API_KEY
    {"playlist_url": "https://www.youtube.com/playlist?list=...", "source_bot": "my-agent"}

Requests are validated, rate limited and de-duplicated before they reach the
indexing queue. The response is ``202 Accepted`` with a job id and a polling URL;
indexing itself happens on the python-backend workers, never inside the request.

The router is built through a small dependency bundle so this module stays free
of a circular import with ``main.py``.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Public YouTube hosts a bot may submit. Anything else is rejected before the
# container ever spends CPU on yt-dlp.
ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}

PLAYLIST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,64}$")

# yt-dlp / YouTube failure signatures -> stable error codes the bot can branch on.
_ERROR_PATTERNS = [
    ("private_playlist", ("private video", "this playlist is private", "playlist is private")),
    ("not_found", ("does not exist", "http error 404", "playlist not found", "removed by the uploader")),
    ("unavailable", ("video unavailable", "this video is unavailable", "no video ids found")),
    ("restricted", ("sign in to confirm your age", "age-restricted", "members-only", "requires payment")),
    ("rate_limited", ("http error 429", "too many requests", "rate limit")),
    ("geo_blocked", ("not available in your country", "geo restricted")),
    # YouTube's anti-bot challenge: retrying from the same egress cannot succeed.
    ("bot_check", ("confirm you're not a bot", "confirm you’re not a bot", "not a bot")),
    # A malformed or deleted playlist id makes YouTube answer 400 to yt-dlp.
    ("invalid_playlist", ("http error 400", "bad request", "incomplete youtube id")),
    ("network_error", ("unable to download", "timed out", "connection refused", "temporary failure")),
]

# Failures that will never succeed on retry; refusing them saves free-tier quota.
TERMINAL_ERRORS = {
    "private_playlist",
    "not_found",
    "unavailable",
    "restricted",
    "geo_blocked",
    "invalid_playlist",
    "bot_check",
}


def classify_playlist_error(message: str) -> Dict[str, Any]:
    """Map a raw yt-dlp error to a stable code plus a bot-friendly retry hint."""
    text = (message or "").lower()
    for code, needles in _ERROR_PATTERNS:
        if any(needle in text for needle in needles):
            return {
                "code": code,
                "retryable": code not in TERMINAL_ERRORS,
                "hint": _HINTS[code],
            }
    return {"code": "index_failed", "retryable": True, "hint": _HINTS["index_failed"]}


_HINTS = {
    "private_playlist": "The playlist is private. Ask the owner for a public link.",
    "not_found": "The playlist does not exist. Re-discover the URL before retrying.",
    "unavailable": "YouTube reports the playlist as unavailable; do not retry now.",
    "restricted": "The playlist needs a signed-in or paid account; this service cannot index it.",
    "rate_limited": "YouTube rate limited the scrape. Retry later with backoff.",
    "geo_blocked": "The playlist is geo-blocked for the scraper's region.",
    "invalid_playlist": "YouTube rejected the playlist id. Re-discover a fresh public URL.",
    "network_error": "Transient network failure between the scraper and YouTube; retry with backoff.",
    "bot_check": "YouTube challenged the scraper (bot check). Retry from an unblocked egress, or supply cookies to yt-dlp.",
    "index_failed": "Unexpected indexing failure. Poll the job for the final status.",
}


class BotIndexIn(BaseModel):
    playlist_url: str = Field(..., min_length=8, max_length=2048)
    source_bot: str = Field("unknown-bot", min_length=1, max_length=120)
    limit: Optional[int] = Field(None, ge=1, le=500)


def validate_playlist_url(raw: str) -> str:
    """Return the normalised URL or raise a 400 with a machine-readable code."""
    value = (raw or "").strip()
    try:
        parsed = urlparse(value)
    except ValueError:
        raise HTTPException(400, detail={"code": "invalid_url", "message": "URL cannot be parsed"})
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            400, detail={"code": "invalid_url", "message": "URL must start with https://"}
        )
    host = (parsed.netloc or "").lower().split(":")[0]
    if host not in ALLOWED_HOSTS:
        raise HTTPException(
            400,
            detail={
                "code": "unsupported_host",
                "message": f"Only public YouTube hosts are accepted, got {host or 'nothing'}",
                "allowed_hosts": sorted(ALLOWED_HOSTS),
            },
        )
    query = parse_qs(parsed.query)
    playlist_id = (query.get("list") or [""])[0]
    if not playlist_id:
        raise HTTPException(
            400,
            detail={
                "code": "not_a_playlist",
                "message": "The URL has no list= parameter; a playlist id is required",
            },
        )
    if not PLAYLIST_ID_RE.fullmatch(playlist_id):
        raise HTTPException(
            400, detail={"code": "invalid_playlist_id", "message": "Malformed playlist id"}
        )
    # Rebuild a canonical URL so the same playlist dedupes across equivalent links.
    canonical = f"https://www.youtube.com/playlist?list={playlist_id}"
    return canonical


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def build_bot_router(
    *,
    enqueue: Callable[..., Any],
    get_job: Callable[[str], Optional[Dict[str, Any]]],
    store: Any,
    rate_limit: int,
    rate_window: int,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/bot", tags=["bot"])

    def require_key(authorization: Optional[str]) -> str:
        expected = (os.environ.get("BOT_INGEST_API_KEY") or "").strip()
        if not expected:
            raise HTTPException(
                503,
                detail={
                    "code": "bot_api_disabled",
                    "message": "BOT_INGEST_API_KEY is not configured on this deployment",
                },
            )
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(
                401,
                detail={"code": "missing_token", "message": "Send Authorization: Bearer <key>"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = authorization.split(" ", 1)[1].strip()
        if not hmac.compare_digest(token, expected):
            raise HTTPException(
                401,
                detail={"code": "invalid_token", "message": "The bot API key is not valid"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        return expected

    def enforce_rate_limit(key: str) -> Dict[str, str]:
        allowed, count, reset_in = store.rate_limit_hit(key, rate_limit, rate_window)
        if not allowed:
            raise HTTPException(
                429,
                detail={
                    "code": "rate_limited",
                    "message": f"Limit is {rate_limit} submissions per {rate_window}s",
                    "retry_after_seconds": reset_in,
                },
                headers={"Retry-After": str(reset_in)},
            )
        return {
            "X-RateLimit-Limit": str(rate_limit),
            "X-RateLimit-Remaining": str(max(0, rate_limit - count)),
            "X-RateLimit-Reset": str(reset_in),
        }

    @router.get("/health")
    def bot_health(authorization: Optional[str] = Header(None)):
        require_key(authorization)
        return {"status": "ok", "queue_accepting": True, "ts": time.time()}

    @router.post("/index-playlist", status_code=202)
    async def index_playlist(
        payload: BotIndexIn,
        request: Request,
        authorization: Optional[str] = Header(None),
        idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    ):
        api_key = require_key(authorization)
        headers = enforce_rate_limit(f"bot:{_digest(api_key)}")

        url = validate_playlist_url(payload.playlist_url)
        key = (idempotency_key or "").strip() or f"{payload.source_bot}:{_digest(url)}"

        existing = store.idempotent_job(key)
        if existing:
            job = get_job(existing)
            if job:
                return JSONResponse(
                    status_code=200,
                    headers=headers,
                    content={
                        "accepted": job.get("status") not in ("error", "skipped"),
                        "duplicate": True,
                        "job": job,
                        "job_status_url": f"/api/v1/bot/jobs/{existing}",
                    },
                )

        job_id = await enqueue(
            url, payload.limit, f"bot:{payload.source_bot}"[:120]
        )
        store.remember_idempotent_job(key, job_id)
        job = get_job(job_id) or {"job_id": job_id, "status": "queued"}
        return JSONResponse(
            status_code=202,
            headers=headers,
            content={
                "accepted": True,
                "duplicate": False,
                "job": job,
                "job_status_url": f"/api/v1/bot/jobs/{job_id}",
                "playlist_url": url,
                "source_bot": payload.source_bot,
                "poll_after_seconds": 5,
            },
        )

    @router.get("/jobs/{job_id}")
    def job_status(job_id: str, authorization: Optional[str] = Header(None)):
        require_key(authorization)
        job = get_job(job_id)
        if not job:
            raise HTTPException(
                404, detail={"code": "unknown_job", "message": "No such job id"}
            )
        body: Dict[str, Any] = {"job": job}
        if job.get("error"):
            body["failure"] = classify_playlist_error(str(job["error"]))
        return body

    @router.get("/playlists/validate")
    def validate(playlist_url: str, authorization: Optional[str] = Header(None)):
        require_key(authorization)
        return {"playlist_url": validate_playlist_url(playlist_url), "valid": True}

    return router
