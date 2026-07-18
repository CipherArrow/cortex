"""Activity feed: a small on-disk trace of which graph nodes AI lookups touch.

Every query/context/neighbors/hubs call (and each incremental sync) appends one
JSON line: {"t": epoch_ms, "action": "...", "ids": [...]}. The live graph view
(`cortex serve`) polls this to glow the nodes and paths an agent is accessing.
Logging is best-effort and must never break a lookup — all errors are swallowed.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .config import Config

ACTIVITY_FILE = "activity.jsonl"
_MAX_BYTES = 512 * 1024   # rotate: keep the tail once the file grows past this
_KEEP_LINES = 500


def _path(cfg: Config) -> Path:
    return cfg.data_dir / ACTIVITY_FILE


def log_touch(cfg: Config, action: str, ids) -> None:
    """Append one activity event. Silent no-op on any failure."""
    try:
        ids = [i for i in ids if i][:200]
        if not ids or not cfg.data_dir.is_dir():
            return
        p = _path(cfg)
        ev = {"t": int(time.time() * 1000), "action": action, "ids": ids}
        # Optional identity tag so multiple concurrent AIs are distinguishable
        # in the feed: export CORTEX_AGENT="claude-code" (or aider, cline, ...).
        agent = os.environ.get("CORTEX_AGENT", "").strip()
        if agent:
            ev["agent"] = agent[:40]
        line = json.dumps(ev, separators=(",", ":"))
        existed = p.exists()
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        if not existed:
            from .secure import harden_file
            harden_file(p)  # the live feed reveals what an agent is doing
        if p.stat().st_size > _MAX_BYTES:
            tail = p.read_text("utf-8").splitlines()[-_KEEP_LINES:]
            p.write_text("\n".join(tail) + "\n", "utf-8")
    except Exception:
        pass


def read_since(cfg: Config, since_ms: int, limit: int = 200) -> list:
    """Return events newer than `since_ms`, oldest first."""
    try:
        p = _path(cfg)
        if not p.is_file():
            return []
        out = []
        for line in p.read_text("utf-8").splitlines()[-2000:]:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("t", 0) > since_ms:
                out.append(ev)
        return out[-limit:]
    except Exception:
        return []
