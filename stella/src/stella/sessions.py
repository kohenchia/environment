"""Per-session bookkeeping: the cursor (last ledger seq shown) and flags."""

from __future__ import annotations

import json
import re
from pathlib import Path

from stella.config import store_dir

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def _path(session_id: str) -> Path:
    return store_dir() / "sessions" / f"{_SAFE.sub('_', session_id or 'unknown')}.json"


def load(session_id: str) -> dict:
    try:
        return json.loads(_path(session_id).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"cursor": 0, "last_addressed": False, "context_loaded": False}


def save(session_id: str, data: dict) -> None:
    p = _path(session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(p)
