"""Qwen3-Embedding tokenizer for the local vocabulary and Jaccard signal.

The local indexer must build its vocabulary and inverted index with the *exact*
tokenizer of the embedding model, otherwise the terms it persists do not line up
with the llama.cpp embeddings. This module is the single loader for
``Qwen/Qwen3-Embedding-0.6B`` and degrades gracefully:

1. ``QWEN3_TOKENIZER_PATH`` points at ``tokenizer.json`` (or the directory that
   contains it). This is what the local indexer mounts into the container.
2. Otherwise ``transformers.AutoTokenizer.from_pretrained(QWEN3_TOKENIZER_ID)``.
3. Otherwise ``tokenizers.Tokenizer.from_pretrained(QWEN3_TOKENIZER_ID)``.
4. Otherwise the module reports ``fallback`` and callers keep the legacy
   whitespace/stem tokenizer, so the serving image still boots without the model
   assets (and without network access).

Nothing here downloads model weights: only the tokenizer assets, and only when a
path or the optional libraries are present.

Encoding note: Qwen3 uses byte-level BPE, so raw tokens are printable stand-ins
for UTF-8 bytes (``\u0120`` for a space, ``Ã©`` for ``é``). :func:`decode_token`
turns one token back into text for logs, the dashboard and vocabulary keys; token
ids and their order stay exactly as the model produced them, so term matching
remains deterministic.
"""

from __future__ import annotations

import os
import re
import threading
from typing import List, Optional, Set

TOKENIZER_ID = (os.environ.get("QWEN3_TOKENIZER_ID") or "Qwen/Qwen3-Embedding-0.6B").strip()
TOKENIZER_PATH = (os.environ.get("QWEN3_TOKENIZER_PATH") or "").strip()
ENABLED = (os.environ.get("QWEN3_TOKENIZER_ENABLED") or "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

# Qwen3 uses ChatML markers; they are structural, never vocabulary terms.
_SPECIAL_RE = re.compile(r"^<\|.*\|>$")
# Byte-level BPE stores UTF-8 bytes as printable Unicode code points (GPT-2's
# bytes_to_unicode mapping). Decode them before display or vocabulary use, so a
# Spanish/Japanese token reads as text instead of "Ã©"/"ãģ“".
_ALNUM_RE = re.compile(r"\w", re.UNICODE)


def _bytes_to_unicode() -> dict:
    """GPT-2/Qwen byte-level BPE alphabet: byte value -> visible character."""
    values = (
        list(range(ord("!"), ord("~") + 1))
        + list(range(ord("\u00a1"), ord("\u00ac") + 1))
        + list(range(ord("\u00ae"), ord("\u00ff") + 1))
    )
    chars = values[:]
    extra = 0
    for byte in range(2**8):
        if byte not in values:
            values.append(byte)
            chars.append(2**8 + extra)
            extra += 1
    return dict(zip(values, (chr(char) for char in chars)))


_BYTE_DECODER = {char: byte for byte, char in _bytes_to_unicode().items()}


def decode_token(token: str) -> str:
    """Best-effort UTF-8 decoding of one byte-level BPE token for display.

    Token *ids* are untouched: only the human-readable term is decoded. A token
    can split a multi-byte codepoint across neighbours, so undecodable bytes
    become U+FFFD rather than raising.
    """
    if not token:
        return ""
    raw = bytearray()
    for char in token:
        byte = _BYTE_DECODER.get(char)
        if byte is None:
            raw.extend(char.encode("utf-8", errors="replace"))
        else:
            raw.append(byte)
    return raw.decode("utf-8", errors="replace")


_LOCK = threading.Lock()
_LOADED = False
_BACKEND = "fallback"
_TOKENIZER = None


def _candidate_file() -> Optional[str]:
    if not TOKENIZER_PATH:
        return None
    if os.path.isdir(TOKENIZER_PATH):
        candidate = os.path.join(TOKENIZER_PATH, "tokenizer.json")
        return candidate if os.path.isfile(candidate) else None
    if os.path.isfile(TOKENIZER_PATH):
        return TOKENIZER_PATH
    return None


def _load() -> None:
    global _LOADED, _BACKEND, _TOKENIZER
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        _LOADED = True
        if not ENABLED:
            print("[lirify] Qwen3 tokenizer disabled (QWEN3_TOKENIZER_ENABLED=0)", flush=True)
            return
        path = _candidate_file()
        if path:
            try:
                from tokenizers import Tokenizer

                _TOKENIZER = Tokenizer.from_file(path)
                _BACKEND = "tokenizers"
                print(f"[lirify] Qwen3 tokenizer loaded from {path}", flush=True)
                return
            except Exception as exc:  # pragma: no cover - optional dependency
                print(f"[lirify] Qwen3 tokenizer file failed ({path}): {exc}", flush=True)
        try:
            from transformers import AutoTokenizer

            _TOKENIZER = AutoTokenizer.from_pretrained(TOKENIZER_ID)
            _BACKEND = "transformers"
            print(f"[lirify] Qwen3 tokenizer loaded via transformers ({TOKENIZER_ID})", flush=True)
            return
        except Exception as exc:  # pragma: no cover - optional dependency
            print(f"[lirify] transformers tokenizer unavailable: {exc}", flush=True)
        try:
            from tokenizers import Tokenizer

            _TOKENIZER = Tokenizer.from_pretrained(TOKENIZER_ID)
            _BACKEND = "tokenizers"
            print(f"[lirify] Qwen3 tokenizer loaded via tokenizers ({TOKENIZER_ID})", flush=True)
            return
        except Exception as exc:  # pragma: no cover - optional dependency
            print(
                "[lirify] Qwen3 tokenizer unavailable; falling back to the legacy "
                f"whitespace/stem tokenizer ({exc})",
                flush=True,
            )
            _TOKENIZER = None
            _BACKEND = "fallback"


def available() -> bool:
    _load()
    return _TOKENIZER is not None


def backend() -> str:
    """"tokenizers" | "transformers" | "fallback"."""
    _load()
    return _BACKEND


def _clean(token: str) -> Optional[str]:
    token = decode_token(token).replace("\n", " ").strip().lower()
    if not token or _SPECIAL_RE.match(token):
        return None
    if not _ALNUM_RE.search(token):
        return None
    return token


def tokenize_terms(text: str) -> List[str]:
    """Subword terms in model order, or ``[]`` when the tokenizer is unavailable.

    Duplicates are preserved so callers can build term frequencies; callers that
    need a set use :func:`token_set`.
    """
    _load()
    if _TOKENIZER is None or not text:
        return []
    try:
        if _BACKEND == "transformers":
            ids = _TOKENIZER.encode(text, add_special_tokens=False)
            raw = _TOKENIZER.convert_ids_to_tokens(ids)
        else:
            raw = _TOKENIZER.encode(text).tokens
    except Exception as exc:  # pragma: no cover - model assets changed
        print(f"[lirify] Qwen3 tokenization failed: {exc}", flush=True)
        return []
    terms: List[str] = []
    for token in raw:
        cleaned = _clean(token)
        if cleaned:
            terms.append(cleaned)
    return terms


def token_set(text: str, ngrams: int = 1) -> Set[str]:
    """Token-set used by the Jaccard signal; optional bigrams/trigrams.

    Qwen3 is byte-level BPE, so the *terms* are subwords. Bigrams are joined with
    ``\x1f`` so they can never collide with a unigram.
    """
    terms = tokenize_terms(text)
    if not terms:
        return set()
    if ngrams <= 1:
        return set(terms)
    out: Set[str] = set()
    for size in range(1, ngrams + 1):
        if size == 1:
            out.update(terms)
            continue
        for start in range(0, len(terms) - size + 1):
            out.add("\x1f".join(terms[start : start + size]))
    return out


def reset_tokenizer() -> None:
    """Test helper: drop the cached tokenizer."""
    global _LOADED, _TOKENIZER, _BACKEND
    with _LOCK:
        _LOADED = False
        _TOKENIZER = None
        _BACKEND = "fallback"
