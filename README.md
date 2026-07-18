# Cortex

**A self-updating knowledge graph for your projects — external memory for AI agents.**

Cortex scans a project into a graph of files, symbols, docs and the links between
them, then saves it as both a readable `MAP.md` and a fast SQLite index. Any AI
agent (or you) can then *look things up* — `cortex query emotion` — instead of
reading the whole codebase into a context window. It stays fresh automatically as
files change.

It works like Obsidian's graph for **prose** projects and like a repo-map for
**code** projects, from one tool, with **zero third-party dependencies** (Python
standard library only).

## Why

Large-context AI still has a memory problem: it re-reads files, burns tokens, and
loses the thread when chats are compressed. Cortex moves the project's structure
*out* of the context window and *onto disk*, where it can be queried on demand.
The design principle: the only thing every AI agent accepts is **plain files plus
a shell command**, so that is all Cortex is.

## Quickstart

```bash
# 1. Make the command available (one time)
ln -s "$PWD/bin/cortex" ~/.local/bin/cortex     # or use: PYTHONPATH=. python3 -m cortex
cortex doctor

# 2. Map a project (first full scan)
cd /path/to/project
cortex scan

# 3. Use it
cortex query <term>            # find a file/symbol/heading
cortex context <symbol>        # definition + callers + callees + siblings
cortex importers <path>        # what depends on this
cortex hubs                    # the most central files — read these first
cortex status                  # freshness

# 4. Keep it fresh
cortex sync                    # incremental; automatic if the hook is installed

# 5. Watch it live (optional)
cortex serve                   # http://127.0.0.1:8377 — the map glows amber
                               # wherever an agent is currently looking
```

## What it extracts

| Language(s) | How | What |
|---|---|---|
| Python | stdlib `ast` (accurate) | modules, classes, functions/methods, imports, inheritance, direct calls |
| JS/TS/Svelte/Vue, Rust, Go, Java/Kotlin, C/C++, Ruby, shell | regexes | top-level definitions + imports |
| Markdown | parser | headings, `[[wikilinks]]`, `[md](links)`, `#tags` |
| YAML/TOML/JSON | parser | top-level config keys |

Cross-references are resolved to internal files where possible (Python dotted +
relative imports, JS relative imports, Rust paths, unique-name matches for
Java/etc.), and everything else becomes an `external` node. Importance is scored
with a built-in PageRank so `hubs` and the map surface the real load-bearing files.

> The regex extractors are a pragmatic default that runs anywhere. The extractor
> interface is pluggable, so a tree-sitter backend can be added later without
> touching the graph, index, or query layers.

## Layout

```
Cortex/
  AGENTS.md            # the agent guide — point any AI here
  README.md            # this file
  bin/cortex           # launcher shim (python -m cortex with PYTHONPATH set)
  cortex/              # the package
    model.py           # Node/Edge dataclasses + stable content-derived ids
    config.py          # scan config: ignores, language table, .cortex/config.toml
    walker.py          # ignore-aware walk + content-hash manifest (incremental)
    extractors/        # python_ast, regex_generic, markdown, config_files
    graph.py           # build, resolve cross-refs, PageRank
    store.py           # graph.json + SQLite/FTS5 index (atomic swaps)
    lockfile.py        # flock so concurrent agents' writes serialize
    query.py           # search / context / neighbors / importers / hubs
    activity.py        # lookup trace feed (.cortex/activity.jsonl) for the live view
    scan.py            # orchestration: full_scan + incremental sync
    emit_markdown.py   # MAP.md + the CORTEX.md pointer
    emit_mermaid.py    # mermaid / dot export
    emit_html.py       # static-atlas interactive graph (deterministic layout)
    serve.py           # localhost live view — glows where agents are looking
    hookgen.py         # prints the Claude Code hook block with resolved paths
    cli.py             # command-line interface
  hooks/               # Claude Code PostToolUse auto-sync hook + install guide
  templates/           # drop-in AGENTS snippet for other projects
  tests/test_smoke.py  # end-to-end test
```

Per scanned project, Cortex writes only `.cortex/` (graph.json, index.db,
manifest.json, config.toml, MAP.md) and a `CORTEX.md` pointer at the root.

## Live view

`cortex serve` hosts the graph at `http://127.0.0.1:8377` as a **static atlas**:
the layout is solved once, deterministically (same structure → same map), and
never moves during interaction. Click a node to light up its connection paths;
scroll to zoom, drag to pan. Because every lookup logs which nodes it touched,
the served page also **glows amber in real time wherever an AI agent is
currently looking** — a live window into the agent's reasoning path. Set
`CORTEX_AGENT=<name>` per tool to tag who touched what.

`cortex graph --format html` writes the same atlas as a standalone offline file
(no server, no live glow).

## Multiple agents at once

Cortex is multi-agent safe: any number of AIs/tools can query one project's map
simultaneously (reads never block), and concurrent writers (scan/sync) serialize
on a per-project lock with atomic index swaps — a reader can never catch a
half-written index. Different models, different tools, same map.

## Auto-update

Three tiers, most-to-least automatic:

1. **Claude Code hook** — installs a `PostToolUse` hook that runs `cortex sync`
   after each Write/Edit. Run `cortex install-hook` for the exact block. It never
   edits your settings automatically.
2. **Convention** — any agent following `CORTEX.md`/`AGENTS.md` runs `cortex sync`
   after changing files.
3. **Manual / scheduled** — `cortex scan` on demand, or from a timer.

## Requirements

Python 3.11+ (uses `tomllib`). Verified on Python 3.14. No other dependencies.

## Test

```bash
PYTHONPATH=. python3 tests/test_smoke.py
```
