"""LangChain tool wrapper for the Lirify playlist indexer.

    from langchain_tool import build_lirify_tools
    tools = build_lirify_tools()

Requires `langchain-core` (and `pydantic` v2). The underlying client is plain
stdlib, so the same behaviour is available outside LangChain.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))

from lirify_playlist import LirifyError, index_playlist, job_status  # noqa: E402

try:
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - optional dependency
    raise SystemExit(
        "langchain-core and pydantic are required for this wrapper: "
        "pip install langchain-core pydantic"
    ) from exc


class IndexPlaylistArgs(BaseModel):
    playlist_url: str = Field(..., description="Public YouTube playlist URL or playlist id.")
    source_bot: str = Field("ai-agent", description="Agent name recorded on the job.")
    limit: Optional[int] = Field(None, ge=1, le=500, description="Index at most N videos.")
    wait: bool = Field(True, description="Poll until the job commits or fails.")
    max_retries: int = Field(
        0,
        ge=0,
        le=5,
        description="Agent-side resubmissions after a retryable failure, with randomised delay.",
    )


class JobStatusArgs(BaseModel):
    job_id: str = Field(..., description="Job id returned by index_youtube_playlist.")


def _index(
    playlist_url: str,
    source_bot: str = "ai-agent",
    limit: Optional[int] = None,
    wait: bool = True,
    max_retries: int = 0,
) -> Dict[str, Any]:
    try:
        return index_playlist(
            playlist_url,
            source_bot=source_bot,
            limit=limit,
            wait=wait,
            max_retries=max_retries,
        )
    except LirifyError as error:
        return error.as_dict()


def _status(job_id: str) -> Dict[str, Any]:
    try:
        return job_status(job_id)
    except LirifyError as error:
        return error.as_dict()


def build_lirify_tools() -> list:
    return [
        StructuredTool.from_function(
            func=_index,
            name="index_youtube_playlist",
            description=(
                "Queue a public YouTube playlist for lyric indexing in Lirify and "
                "optionally wait for completion. Returns a job id plus status."
            ),
            args_schema=IndexPlaylistArgs,
        ),
        StructuredTool.from_function(
            func=_status,
            name="playlist_index_job_status",
            description="Poll a Lirify indexing job by id.",
            args_schema=JobStatusArgs,
        ),
    ]


if __name__ == "__main__":  # tiny smoke test: python langchain_tool.py PLxxxx
    import json

    if len(sys.argv) > 1:
        print(json.dumps(index_playlist(sys.argv[1], source_bot="langchain-cli"), indent=2))
