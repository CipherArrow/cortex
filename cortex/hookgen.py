"""Render the ready-to-paste Claude Code auto-sync hook instructions.

We never edit settings.json automatically — this just prints the exact block and
where it goes, so the user (or an agent, with consent) can install it.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import CLI_NAME, TOOL_NAME

INSTALL_ROOT = Path(__file__).resolve().parent.parent  # the Cortex repo root
HOOK_SCRIPT = INSTALL_ROOT / "hooks" / "cortex_hook.py"


def hook_block() -> dict:
    """The PostToolUse hook entry to merge into ~/.claude/settings.json."""
    return {
        "PostToolUse": [
            {
                "matcher": "Write|Edit|MultiEdit",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"python3 {HOOK_SCRIPT}",
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

1) Ensure the hook script is executable:
     chmod +x {HOOK_SCRIPT}

2) Merge this into the "hooks" object of ~/.claude/settings.json
   (keep any existing hooks — add PostToolUse alongside them):

{block}

3) Restart Claude Code (or start a new session) so the hook loads.

Notes:
- The hook finds the nearest ancestor directory containing a `.cortex/` folder,
  so only initialised projects are touched.
- It exits 0 and stays silent on anything it can't handle, so it never blocks work.
- Other agents that cannot run hooks should instead follow the convention in each
  project's CORTEX.md: run `{CLI_NAME} sync` after creating or editing files.
"""
