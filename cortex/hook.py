"""Editor/agent hook body: sync the map for a file that was just written.

Lives inside the package (not in `hooks/`) so it is present in an installed
copy as well as a source checkout — a wheel ships `cortex/`, not the repo's
top-level directories.

Reads the Claude Code PostToolUse JSON on stdin, finds the file that was
written or edited, locates the nearest ancestor project containing `.cortex/`,
and runs an incremental sync for just that file. Silent and non-blocking:
anything it cannot handle exits 0, because a map refresh must never fail a
user's edit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _find_project(path: Path) -> Path | None:
    for cand in [path, *path.parents]:
        if (cand / ".cortex").is_dir():
            return cand
    return None


def run(stream=None) -> int:
    try:
        raw = (stream or sys.stdin).read()
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
        from . import scan
        scan.sync(str(project), changed=[str(target)])
    except Exception:
        return 0
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
