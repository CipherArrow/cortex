# Cortex auto-sync hook (Claude Code)

This keeps every Cortex-mapped project fresh automatically: after Claude Code
writes or edits a file, the hook runs an incremental `cortex sync` for the
project that owns that file. It is a silent no-op for files outside a Cortex
project, and it never blocks work (any error → exit 0).

## Install

1. Get the exact settings block. `install-hook` resolves the right command for
   how *your* copy of Cortex is installed, so run it rather than copying a
   command from this page:

   ```bash
   cortex install-hook
   ```

2. Merge the printed `PostToolUse` entry into the `"hooks"` object of
   `~/.claude/settings.json`, **keeping any hooks already there**:

   ```json
   {
     "hooks": {
       "PostToolUse": [
         {
           "matcher": "Write|Edit|MultiEdit|NotebookEdit",
           "hooks": [
             { "type": "command",
               "command": "<what install-hook printed>",
               "timeout": 15 }
           ]
         }
       ]
     }
   }
   ```

3. Restart Claude Code (or start a new session) so the hook loads.

## Why the command differs by install

The hook body lives in the package (`cortex/hook.py`), so it exists in every
install, and `install-hook` prints whichever entry point can actually reach it:

| How you installed | Command it prints |
|---|---|
| `pipx install` / `pip install` | `<that env's python> -m cortex hook` |
| Clone + `bin/cortex` on PATH | `<clone>/bin/cortex hook` |

This matters most for **pipx**, which isolates Cortex in its own virtualenv — a
bare `python3` would not find the package, so the hook must name the interpreter
that has it. The shim in a clone sets `PYTHONPATH` itself, so it needs nothing
on PATH.

`hooks/cortex_hook.py` still works and still delegates to the same code, so an
existing settings.json pointing at it needs no change.

## How it works

- Reads the hook JSON on stdin, pulls `tool_input.file_path`.
- Walks up from that file to the nearest ancestor directory containing a
  `.cortex/` folder — so only initialised projects are ever touched.
- Runs an incremental sync for that project (re-reads only the changed file,
  then re-resolves and re-ranks).

On a very large repo, syncing per save costs about as much as syncing after a
burst of edits — see the `sync` contract in `AGENTS.md` before wiring this into
a monorepo.

## Other agents

Agents that can't run hooks should follow each project's `CORTEX.md`: run
`cortex sync` after creating or editing files. Same effect, done by convention
instead of automatically.
