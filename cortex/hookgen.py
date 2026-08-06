"""Render the ready-to-paste Claude Code auto-sync hook instructions.

We never edit settings.json automatically — this just prints the exact block and
where it goes, so the user (or an agent, with consent) can install it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import CLI_NAME, TOOL_NAME

INSTALL_ROOT = Path(__file__).resolve().parent.parent  # repo root, in a checkout


def hook_command() -> str:
    """The command to run the auto-sync hook, for however Cortex is installed.

    A source checkout has `bin/cortex` beside the package, and that shim sets
    PYTHONPATH itself — the one thing guaranteed to work without assuming the
    repo is importable. Otherwise Cortex is installed, and the interpreter
    running us already has the package on its path. That second case matters
    for pipx especially: it isolates Cortex in its own virtualenv, so a bare
    `python3` would not find it.
    """
    shim = INSTALL_ROOT / "bin" / CLI_NAME
    if shim.is_file():
        return f"{shim} hook"
    return f"{sys.executable} -m cortex hook"


def hook_block() -> dict:
    """The PostToolUse hook entry to merge into ~/.claude/settings.json."""
    return {
        "PostToolUse": [
            {
                "matcher": "Write|Edit|MultiEdit|NotebookEdit",
                "hooks": [
                    {
                        "type": "command",
                        "command": hook_command(),
                        "timeout": 15,
                    }
                ],
            }
        ]
    }


def render_hook_instructions() -> str:
    block = json.dumps(hook_block(), indent=2)
    return f"""\
{TOOL_NAME} auto-sync hook (Claude Code)
{'=' * 40}

This keeps every {TOOL_NAME}-mapped project fresh automatically: after Claude Code
writes or edits a file, the hook runs `{CLI_NAME} sync --changed <file>` for the
project that owns it. It is a no-op for files outside a {TOOL_NAME} project.

1) Merge this into the "hooks" object of ~/.claude/settings.json
   (keep any existing hooks — add PostToolUse alongside them):

{block}

2) Restart Claude Code (or start a new session) so the hook loads.

Notes:
- The hook finds the nearest ancestor directory containing a `.cortex/` folder,
  so only initialised projects are touched.
- It exits 0 and stays silent on anything it can't handle, so it never blocks work.
- Other agents that cannot run hooks should instead follow the convention in each
  project's CORTEX.md: run `{CLI_NAME} sync` after creating or editing files.
"""
