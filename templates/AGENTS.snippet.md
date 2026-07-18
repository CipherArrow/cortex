<!--
Drop-in block for ANY project's AGENTS.md or CLAUDE.md.
Paste the section below so every agent working in that project adopts Cortex.
Adjust the install path if Cortex lives elsewhere.
-->

## Project memory: Cortex

This project is mapped by **Cortex**, a self-updating knowledge graph. Use it as
external memory so you don't have to read the whole tree into context.

**Before exploring:**
- `cortex query <term>` — locate a file/symbol/heading by name or summary
- `cortex context <symbol>` — its definition, callers, callees, siblings
- `cortex importers <path>` — what depends on a file
- `cortex hubs` — the most central files (read these first)
- or read `.cortex/MAP.md` directly (plain Markdown; no shell needed)

**Prefer a lookup to a full-file read** — read the exact `path:line` Cortex
returns, not the whole file. This is the main token/context saving.

**After creating or editing files:** run `cortex sync` (automatic if the Cortex
PostToolUse hook is installed).

If `cortex` isn't on PATH, use:
`PYTHONPATH=/path/to/Cortex python3 -m cortex <args>`

Full guide: `AGENTS.md` in the Cortex repo.
