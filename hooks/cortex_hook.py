#!/usr/bin/env python3
"""Claude Code PostToolUse hook: auto-sync the Cortex map for edited files.

Reads the hook JSON on stdin, finds the file that was written/edited, locates the
nearest ancestor project containing a `.cortex/` dir, and runs an incremental
sync for just that file. Silent and non-blocking: any problem -> exit 0.
"""

import json
import os
import sys
from pathlib import Path

# Make the `cortex` package importable regardless of cwd.
INSTALL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(INSTALL_ROOT))


def _find_project(path: Path):
    for cand in [path, *path.parents]:
        if (cand / ".cortex").is_dir():
            return cand
    return None


def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    tin = data.get("tool_input") or {}
    fp = tin.get("file_path") or tin.get("path") or tin.get("notebook_path")
    if not fp:
        return 0

    try:
        target = Path(fp).resolve()
    except Exception:
        return 0

    project = _find_project(target if target.exists() else target.parent)
    if project is None:
        return 0  # file isn't inside a Cortex-mapped project

    try:
        from cortex import scan
        scan.sync(str(project), changed=[str(target)])
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
