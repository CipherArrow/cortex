#!/usr/bin/env python3
"""Compatibility shim for the Claude Code PostToolUse auto-sync hook.

The hook body moved into the package (`cortex/hook.py`) so it also exists in a
pip/pipx install, where the repo's top-level `hooks/` directory is not present.
This file stays so that any settings.json already pointing at it keeps working
untouched — `cortex install-hook` now prints the packaged form for new setups.

Silent and non-blocking, like the hook it delegates to: any problem -> exit 0.
"""

import sys
from pathlib import Path

# Source checkout: make the sibling `cortex` package importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from cortex.hook import main
except Exception:
    def main() -> int:      # never fail an edit because the map could not load
        return 0


if __name__ == "__main__":
    sys.exit(main())
