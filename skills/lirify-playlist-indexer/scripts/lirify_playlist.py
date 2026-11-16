#!/usr/bin/env python3
"""Lirify bot ingestion client: validate a public YouTube playlist, submit it for
indexing, and poll the job until it finishes.

Standard library only, so it runs unchanged inside an OpenAI/Anthropic tool loop,
an MCP server, a LangChain tool, a CI job or a bare container.

Environment
-----------
LIRIFY_BOT_API_URL   Base URL of python-backend (default: http://127.0.0.1:8000)
LIRIFY_BOT_API_KEY   Bearer token configured as BOT_INGEST_API_KEY on the server
LIRIFY_BOT_TIMEOUT   Total seconds to wait for a job (default: 900)

Exit codes
----------
0  job committed (or already committed)
1  unexpected error
2  invalid/unsupported playlist URL
3  authentication failure (missing or wrong key)
4  rate limited
5  job failed permanently (private, deleted, geo-blocked, bot check, ...)
6  timed out while waiting (job may still be running; poll it again later)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, Optional, Tuple

DEFAULT_BASE_URL = "http://127.0.0.1:8000"

ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}

PLAYLIST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

TERMINAL_FAILURES = {
    "private_playlist",
    "not_found",
    "unavailable",
    "restricted",
    "geo_blocked",
    "invalid_playlist",
    "bot_check",
    "gave_up",
}

TERMINAL_STATUSES = {"committed", "skipped", "error"}


class LirifyError(Exception):
    """Carries a machine-readable code plus the HTTP status that produced it."""

    def __init__(self, code: str, message: str, status: int = 0, retry_after: int = 0, hint: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retry_after = retry_after
        self.hint = hint

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "http_status": self.status,
                "retry_after_seconds": self.retry_after,
                "hint": self.hint,
            },
        }


# ---------------------------------------------------------------------------
# URL handling
# ---------------------------------------------------------------------------


def normalize_playlist_url(raw: str) -> str:
    """Accept any public YouTube playlist variant and return a canonical URL.

    Accepts:
      https://www.youtube.com/playlist?list=PL...
      https://music.youtube.com/playlist?list=OLAK5uy_...
      https://www.youtube.com/watch?v=...&list=PL...
      https://youtu.be/...?list=PL...
      a bare playlist id (PL..., UU..., OLAK5uy_..., FL..., RD...)
    """
    value = (raw or "").strip()
    if not value:
        raise LirifyError("invalid_url", "The playlist URL is empty")

    # Bare playlist id: build a canonical URL.
    if PLAYLIST_ID_RE.fullmatch(value) and "://" not in value:
        return f"https://www.youtube.com/playlist?list={value}"

    if not value.startswith(("http://", "https://")):
        value = "https://" + value

    parsed = urllib.parse.urlparse(value)
    host = (parsed.netloc or "").lower().split(":")[0]
    if host not in ALLOWED_HOSTS:
        raise LirifyError(
            "unsupported_host",
            f"Only public YouTube hosts are accepted, got '{host or 'nothing'}'",
            hint="Use a youtube.com, music.youtube.com or youtu.be link.",
        )

    query = urllib.parse.parse_qs(parsed.query)
    playlist_id = (query.get("list") or [""])[0]
    if not playlist_id:
        video_id = ""
        if host.endswith("youtu.be"):
            video_id = parsed.path.strip("/").split("/")[0]
        else:
            video_id = (query.get("v") or [""])[0]
        if video_id and VIDEO_ID_RE.fullmatch(video_id):
            raise LirifyError(
                "not_a_playlist",
                "That is a single video, not a playlist (no list= parameter)",
                hint="Ask for the playlist URL, or use the video's 'Save to playlist' page.",
            )
        raise LirifyError(
            "not_a_playlist",
            "The URL has no list= parameter, so there is no playlist to index",
        )

    if not PLAYLIST_ID_RE.fullmatch(playlist_id):
        raise LirifyError("invalid_playlist_id", "The playlist id is malformed")

    return f"https://www.youtube.com/playlist?list={playlist_id}"


def looks_like_playlist(text: str) -> bool:
    try:
        normalize_playlist_url(text)
        return True
    except LirifyError:
        return False


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _base_url() -> str:
    return (os.environ.get("LIRIFY_BOT_API_URL") or DEFAULT_BASE_URL).rstrip("/")


def _api_key() -> str:
    key = (os.environ.get("LIRIFY_BOT_API_KEY") or "").strip()
    if not key:
        raise LirifyError(
            "missing_api_key",
            "LIRIFY_BOT_API_KEY is not set",
            hint="Export the Bearer token that matches BOT_INGEST_API_KEY on the server.",
        )
    return key


def _request(
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    idempotency_key: str = "",
    timeout: int = 60,
) -> Tuple[int, Dict[str, Any]]:
    url = f"{_base_url()}{path}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Accept": "application/json",
    }
    if body:
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8") or "{}"
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace") or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"detail": raw}
        detail = data.get("detail")
        if isinstance(detail, dict):
            code = detail.get("code", "http_error")
            message = detail.get("message") or raw
            retry_after = int(detail.get("retry_after_seconds") or exc.headers.get("Retry-After") or 0)
        else:
            code = "http_error"
            message = str(detail or raw)
            retry_after = int(exc.headers.get("Retry-After") or 0)
        hint = ""
        if exc.code == 401:
            code, hint = "unauthorized", "Check LIRIFY_BOT_API_KEY."
        elif exc.code == 429:
            hint = "Wait retry_after_seconds, then resubmit."
        elif exc.code == 503:
            hint = "Bot ingestion is disabled on this deployment (BOT_INGEST_API_KEY unset)."
        raise LirifyError(code, message, status=exc.code, retry_after=retry_after, hint=hint)
    except urllib.error.URLError as exc:
        raise LirifyError(
            "network_error",
            f"Could not reach {url}: {exc.reason}",
            hint="Check LIRIFY_BOT_API_URL and that the service is awake (Cloud Run scales to zero).",
        )


# ---------------------------------------------------------------------------
# Public operations
# ---------------------------------------------------------------------------


def validate(playlist_url: str) -> Dict[str, Any]:
    canonical = normalize_playlist_url(playlist_url)
    status, data = _request(
        "GET",
        "/api/v1/bot/playlists/validate?" + urllib.parse.urlencode({"playlist_url": canonical}),
    )
    return {"ok": status == 200, "playlist_url": data.get("playlist_url", canonical)}


def submit(
    playlist_url: str,
    source_bot: str = "ai-agent",
    limit: Optional[int] = None,
    idempotency_key: str = "",
) -> Dict[str, Any]:
    canonical = normalize_playlist_url(playlist_url)
    payload: Dict[str, Any] = {"playlist_url": canonical, "source_bot": source_bot[:120]}
    if limit:
        payload["limit"] = int(limit)

    key = idempotency_key or f"{source_bot}:{uuid.uuid4().hex}"
    status, data = _request("POST", "/api/v1/bot/index-playlist", payload, idempotency_key=key)
    job = data.get("job") or {}
    return {
        "ok": status in (200, 202),
        "accepted": bool(data.get("accepted", status == 202)),
        "duplicate": bool(data.get("duplicate")),
        "http_status": status,
        "playlist_url": data.get("playlist_url", canonical),
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "status_url": data.get("job_status_url") or (f"/api/v1/bot/jobs/{job.get('job_id')}" if job.get("job_id") else ""),
        "poll_after_seconds": data.get("poll_after_seconds", 5),
        "idempotency_key": key,
    }


def job_status(job_id: str) -> Dict[str, Any]:
    _, data = _request("GET", f"/api/v1/bot/jobs/{urllib.parse.quote(job_id)}")
    job = data.get("job") or {}
    failure = data.get("failure") or {}
    return {
        "ok": True,
        "job_id": job.get("job_id", job_id),
        "status": job.get("status"),
        "stage": job.get("stage"),
        "added": job.get("added", 0),
        "attempts": job.get("attempts", 0),
        "error": job.get("error") or "",
        "error_code": job.get("error_code") or failure.get("code") or "",
        "retryable": failure.get("retryable"),
        "hint": failure.get("hint", ""),
        "done": job.get("status") in TERMINAL_STATUSES,
    }


def wait_for_job(
    job_id: str,
    timeout: Optional[float] = None,
    interval: float = 5.0,
    quiet: bool = True,
) -> Dict[str, Any]:
    total = float(timeout if timeout is not None else os.environ.get("LIRIFY_BOT_TIMEOUT", "900"))
    deadline = time.time() + total
    seen: Dict[str, Any] = {}
    while time.time() < deadline:
        seen = job_status(job_id)
        if not quiet:
            print(
                f"[{seen.get('status')}] stage={seen.get('stage')} added={seen.get('added')}",
                file=sys.stderr,
            )
        if seen.get("done"):
            return seen
        time.sleep(max(1.0, interval))
    seen["timed_out"] = True
    seen["ok"] = False
    return seen


def index_playlist(
    playlist_url: str,
    source_bot: str = "ai-agent",
    limit: Optional[int] = None,
    wait: bool = True,
    timeout: Optional[float] = None,
    idempotency_key: str = "",
) -> Dict[str, Any]:
    """One-call helper used by the MCP server and the LangChain tool."""
    submitted = submit(playlist_url, source_bot=source_bot, limit=limit, idempotency_key=idempotency_key)
    if not wait or not submitted.get("job_id"):
        return submitted
    final = wait_for_job(submitted["job_id"], timeout=timeout)
    return {**submitted, "final": final, "ok": bool(final.get("status") == "committed")}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print(payload: Dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    if payload.get("ok"):
        print(f"OK  {payload.get('job_id')}  status={payload.get('status') or (payload.get('final') or {}).get('status')}")
    else:
        error = payload.get("error") or {}
        print(f"FAILED  {error.get('code')}: {error.get('message')}", file=sys.stderr)
        if error.get("hint"):
            print(f"hint: {error['hint']}", file=sys.stderr)


def _exit_code(error: LirifyError) -> int:
    """Map an API failure to the documented CLI exit code."""
    if error.status in (401, 403):
        return 3
    if error.status == 429:
        return 4
    if error.status in (400, 404, 422):
        return 2
    if error.code in ("invalid_url", "unsupported_host", "not_a_playlist", "invalid_playlist_id"):
        return 2
    if error.code in ("missing_api_key", "unauthorized", "invalid_token"):
        return 3
    if error.code == "rate_limited":
        return 4
    if error.code in TERMINAL_FAILURES:
        return 5
    return 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lirify-playlist",
        description="Submit a public YouTube playlist to Lirify for lyric indexing.",
    )
    parser.add_argument("command", choices=["submit", "status", "wait", "validate"])
    parser.add_argument("target", help="Playlist URL / id (submit, validate) or job id (status, wait)")
    parser.add_argument("--source-bot", default=os.environ.get("LIRIFY_SOURCE_BOT", "ai-agent"))
    parser.add_argument("--limit", type=int, default=None, help="Index at most N videos from the playlist")
    parser.add_argument("--no-wait", action="store_true", help="Return as soon as the job is accepted")
    parser.add_argument("--timeout", type=float, default=None, help="Seconds to wait for completion")
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            result = validate(args.target)
            _print(result, args.json)
            return 0 if result.get("ok") else 2
        if args.command == "submit":
            result = index_playlist(
                args.target,
                source_bot=args.source_bot,
                limit=args.limit,
                wait=not args.no_wait,
                timeout=args.timeout,
                idempotency_key=args.idempotency_key,
            )
            _print(result, args.json)
            if result.get("timed_out"):
                return 6
            if result.get("ok"):
                return 0
            code = (result.get("final") or {}).get("error_code") or "index_failed"
            return 5 if code in TERMINAL_FAILURES else 1
        if args.command == "status":
            result = job_status(args.target)
            _print(result, args.json)
            return 0
        final = wait_for_job(args.target, timeout=args.timeout)
        _print(final, args.json)
        if final.get("timed_out"):
            return 6
        return 0 if final.get("status") in ("committed", "skipped") else 5
    except LirifyError as error:
        _print(error.as_dict(), args.json)
        return _exit_code(error)


if __name__ == "__main__":
    sys.exit(main())
