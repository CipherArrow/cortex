# Cortex — agent guide

**Read this file first, then operate the tool.** Cortex is a self-updating
knowledge graph of a project. It exists so you (any AI agent, any model) can
*look things up* instead of reading the whole tree into your context window —
saving tokens and surviving chat compression by using the project on disk as
external memory.

This document is model-agnostic: Claude Code, Cursor, Aider, a local LLM with a
shell tool, or a human can all follow it. If you can read a Markdown file and run
a shell command, you can use Cortex.

## Purpose

- Turn a project into a graph of **nodes** (files, modules, classes, functions,
  methods, markdown headings, config keys, concepts) and **edges** (imports,
  calls, inheritance, wikilinks, markdown links, contains, tags).
- Persist it two ways: a human/AI-readable `MAP.md` and a queryable SQLite index.
- Keep it fresh automatically as files are created and edited.

## Ownership

- This repo (`Cortex/`) is the **tool**. It is stdlib-only Python — no pip installs.
- The **map of a project** lives inside that project as a hidden `.cortex/` folder
  plus a visible `CORTEX.md` pointer at its root — exactly like `.git/`. Cortex
  never writes a project's map anywhere but that project.
- Cortex only ever **adds** `.cortex/` and `CORTEX.md`. It does not modify source.

## Setup (once per machine)

```bash
# Put the launcher on PATH (adjust the path to where this repo lives):
ln -s /path/to/Cortex/bin/cortex ~/.local/bin/cortex
cortex doctor          # confirms python + sqlite fts5
```

If you cannot add it to PATH, every command also works as:
```bash
PYTHONPATH=/path/to/Cortex python3 -m cortex <args>
```

## Setup (once per project)

```bash
cd /path/to/some/project
cortex scan            # first full scan; writes .cortex/ and CORTEX.md
```

That is the "map everything for the first time" step. Re-runnable anytime.

## Operating protocol (what an agent should DO)

1. **Before exploring a project, orient with the map, not with file reads.**
   - `cortex query <term>` — find a file/symbol/heading by name or summary.
   - `cortex context <symbol>` — a symbol's definition line, callers, callees, siblings.
   - `cortex importers <path>` — what depends on a file (reverse dependencies).
   - `cortex hubs` — the most central (most depended-upon) files. Read these first.
   - `cortex neighbors <ref>` — every edge in/out of a node.
   - Or just read `.cortex/MAP.md` directly (safe for any model, no shell needed).

2. **Prefer a lookup to a full-file read.** A `query`/`context` result is a few
   hundred tokens; the files it points to may be tens of thousands. Read the
   specific `path:line` the graph gives you, not the whole file.

3. **After you create or edit files, refresh the map:**
   ```bash
   cortex sync                       # incremental: only re-reads changed files
   cortex sync --changed path/to/file.py   # target a specific file
   ```
   If the Claude Code hook is installed (see `hooks/`), this happens
   automatically after every Write/Edit — you do not need to call it yourself.

4. **If something looks stale**, `cortex status` shows how many files changed
   since the last scan; `cortex scan` rebuilds from scratch (authoritative).

Add `--json` to any read command for structured output.

## Local Contracts

- **Node ids are stable** (`sha1(path::qualname)`), so re-scanning is idempotent
  and incremental updates diff cleanly. Do not depend on id *values*; treat them
  as opaque.
- **Call edges are direct-call only** (`helper()`), never `obj.method()` — method
  calls can't be resolved by name without type info, and false edges mislead. So
  "called by" is high-precision but not exhaustive; `imports`/`references`/
  `inherits` are the reliable dependency edges.
- **`MAP.md` is generated** — never hand-edit it; edit source and run `cortex sync`.
- **The graph is best-effort, not a compiler.** It is a navigation aid. When the
  graph and the code disagree, the code wins — re-scan and trust the source.
- **Multi-agent safe.** Any number of AIs/tools may use one project's map at
  once: reads never block; writers (scan/sync) serialize on `.cortex/.lock`
  (flock) and land the index/graph/manifest via atomic rename, so readers always
  see a complete index. Optionally set `CORTEX_AGENT=<name>` so your lookups are
  attributable in the activity feed.
- **Lookups leave a trace.** Every query/context/neighbors/hubs call (and each
  sync) appends the touched node ids to `.cortex/activity.jsonl` (auto-rotated,
  local-only). `cortex serve` reads it to glow the map live; nothing else
  consumes it, and deleting it is always safe.

## Commands

| Command | Purpose |
|---|---|
| `cortex scan` | Full (re)scan of the project |
| `cortex sync [--changed F …]` | Incremental update of changed files |
| `cortex query <term> [--kind K] [-n N]` | Find nodes by name/summary |
| `cortex context <ref>` | Definition + callers + callees + siblings |
| `cortex importers <ref>` | Reverse dependencies |
| `cortex neighbors <ref>` | All edges of a node |
| `cortex hubs [-n N] [--kind K]` | Most central nodes |
| `cortex status` | Stats + staleness |
| `cortex graph --format mermaid\|dot\|html\|json` | Export for visualization (html = static atlas) |
| `cortex serve [--port 8377]` | Live graph on localhost — glows amber where agents are looking |
| `cortex install-hook` | Print the Claude Code auto-sync hook block |
| `cortex doctor` | Environment check |

`<ref>` accepts a symbol name (`Engine`, `emotion.appraise`), a file path
(`core/engine.py`), or a node id.

## How this saves tokens (the point)

- **Instead of** `read core/engine.py` (3,000 lines) to find where emotion is
  applied, run `cortex query emotion` → get `core/emotion.py:88 class EmotionEngine`
  and `core/engine.py:412 _apply_emotion`, then read only those lines.
- **Instead of** re-reading a whole module after compression to remember its
  shape, run `cortex context <symbol>` for a compact "context pack".
- **Instead of** grepping the tree to learn what breaks if you change a file, run
  `cortex importers <path>`.

## Working with a local LLM

A local model that can't run shell tools still benefits: point it at
`.cortex/MAP.md` (plain Markdown) as its map, and at `.cortex/graph.json`
(nodes + edges) if it can parse JSON. A model that *can* run a shell tool uses
the commands above exactly like any other agent.

## Verification

```bash
PYTHONPATH=/path/to/Cortex python3 tests/test_smoke.py
```
Builds a tiny mixed Python/JS/Markdown project, scans it, and asserts that
imports, wikilinks, headings, queries, and incremental sync all work.

## Child DOX Index

- [README.md](README.md) — human-facing overview and quickstart
- [hooks/](hooks/) — Claude Code PostToolUse auto-sync hook + install notes
- [templates/AGENTS.snippet.md](templates/AGENTS.snippet.md) — drop-in block to
  add to any *other* project's AGENTS.md/CLAUDE.md so its agents adopt Cortex
- [cortex/](cortex/) — the Python package (scan → extract → graph → persist → query)
