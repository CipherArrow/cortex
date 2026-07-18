"""Filesystem and text hardening helpers.

Cortex's index can reveal a project's whole structure and (via the live feed)
what an agent is doing, so the on-disk `.cortex/` is kept owner-only. These
helpers centralise permission-setting and untrusted-text cleaning.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

DIR_MODE = 0o700    # rwx for owner only — other local users can't even list
FILE_MODE = 0o600   # rw for owner only

# C0/C1 control chars plus U+2028/U+2029 (line/paragraph separators that can be
# abused for injection). Built from code points so no odd bytes live in source.
_CTRL = re.compile(
    "[" + "".join(chr(c) for c in list(range(0x00, 0x09)) + [0x0b, 0x0c]
                  + list(range(0x0e, 0x20)) + [0x7f, 0x2028, 0x2029]) + "]"
)


def secure_dir(path: Path) -> Path:
    """Create `path` (and parents) and lock it to the owner."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, DIR_MODE)
    except OSError:
        pass
    return path


def harden_file(path: Path, mode: int = FILE_MODE) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def clean_text(s: str, limit: int = 200) -> str:
    """Neutralise untrusted free text (docstrings, headings) before it lands in
    generated docs/tooltips: strip control chars, collapse all whitespace to
    single spaces (kills embedded newlines used for injection), and cap length.
    """
    if not s:
        return ""
    s = _CTRL.sub("", s)
    s = " ".join(s.split())
    return s[:limit]


def within_root(path: str | Path, root: str | Path) -> bool:
    """True if the resolved `path` stays inside the resolved `root`."""
    try:
        rp = os.path.realpath(path)
        rr = os.path.realpath(root)
        return rp == rr or rp.startswith(rr + os.sep)
    except OSError:
        return False
