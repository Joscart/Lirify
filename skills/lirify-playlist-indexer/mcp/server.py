#!/usr/bin/env python3
"""Minimal MCP (Model Context Protocol) server for the Lirify playlist indexer.

Speaks JSON-RPC 2.0 over stdio, so it works with Claude Desktop, Cursor, Zed, the
OpenAI Agents SDK bridge, or any MCP client — no SDK dependency required.

Register it (Claude Desktop example, ~/.config/claude/claude_desktop_config.json):

  {
    "mcpServers": {
      "lirify": {
        "command": "python3",
        "args": ["/absolute/path/to/skills/lirify-playlist-indexer/mcp/server.py"],
        "env": {
          "LIRIFY_BOT_API_URL": "https://lirify-api-xxxxx-uc.a.run.app",
          "LIRIFY_BOT_API_KEY": "…"
        }
      }
    }
  }

Tools
-----
validate_youtube_playlist  Validate/normalise a public YouTube playlist URL.
index_youtube_playlist     Submit it for indexing and (optionally) wait for the job.
playlist_index_job_status  Poll an existing job id.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from lirify_playlist import LirifyError, index_playlist, job_status, normalize_playlist_url  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "lirify-playlist-indexer", "version": "1.0.0"}

TOOLS = [
    {
        "name": "validate_youtube_playlist",
        "description": (
            "Validate and normalise a public YouTube playlist URL (youtube.com, "
            "music.youtube.com or youtu.be). Use this before indexing to fail fast "
            "on single videos, private-looking links or non-YouTube URLs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "playlist_url": {"type": "string", "description": "Playlist URL or bare playlist id."}
            },
            "required": ["playlist_url"],
        },
    },
    {
        "name": "index_youtube_playlist",
        "description": (
            "Queue a public YouTube playlist for lyric indexing in Lirify. Returns a "
            "job id; when wait=true it polls until the job is committed or fails. "
            "Handles invalid URLs, authentication, rate limits and private/deleted "
            "playlists with a machine-readable error code."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "playlist_url": {"type": "string"},
                "source_bot": {
                    "type": "string",
                    "description": "Name of the agent submitting the playlist (audit trail).",
                    "default": "ai-agent",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Index at most N videos from the playlist.",
                },
                "wait": {
                    "type": "boolean",
                    "default": True,
                    "description": "Poll until the job finishes (default) or return immediately.",
                },
                "timeout_seconds": {"type": "number", "default": 900},
            },
            "required": ["playlist_url"],
        },
    },
    {
        "name": "playlist_index_job_status",
        "description": "Poll the status of a previously submitted Lirify indexing job.",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
]


def _text(payload: Dict[str, Any], is_error: bool = False) -> Dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}],
        "isError": is_error,
    }


def call_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if name == "validate_youtube_playlist":
            canonical = normalize_playlist_url(arguments.get("playlist_url", ""))
            return _text({"ok": True, "playlist_url": canonical, "valid": True})
        if name == "index_youtube_playlist":
            result = index_playlist(
                arguments.get("playlist_url", ""),
                source_bot=arguments.get("source_bot") or "ai-agent",
                limit=arguments.get("limit"),
                wait=bool(arguments.get("wait", True)),
                timeout=arguments.get("timeout_seconds"),
            )
            return _text(result, is_error=not result.get("ok"))
        if name == "playlist_index_job_status":
            return _text(job_status(arguments.get("job_id", "")))
        return _text({"ok": False, "error": {"code": "unknown_tool", "message": name}}, is_error=True)
    except LirifyError as error:
        return _text(error.as_dict(), is_error=True)
    except Exception as error:  # pragma: no cover - defensive
        return _text(
            {"ok": False, "error": {"code": "internal_error", "message": str(error)}},
            is_error=True,
        )


def handle(request: Dict[str, Any]) -> Dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": SERVER_INFO,
                "capabilities": {"tools": {"listChanged": False}},
            },
        }
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = request.get("params") or {}
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": call_tool(params.get("name", ""), params.get("arguments") or {}),
        }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}), flush=True)
            continue
        response = handle(request)
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
