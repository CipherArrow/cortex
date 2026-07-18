# Cortex auto-sync hook (Claude Code)

This keeps every Cortex-mapped project fresh automatically: after Claude Code
writes or edits a file, the hook runs an incremental `cortex sync` for the
project that owns that file. It is a silent no-op for files outside a Cortex
project, and it never blocks work (any error → exit 0).

## Install

1. Make the hook script executable:
   ```bash
   chmod +x /path/to/Cortex/hooks/cortex_hook.py
   ```

2. Get the exact settings block (paths are filled in for this machine):
   ```bash
   cortex install-hook
   ```

3. Merge the printed `PostToolUse` entry into the `"hooks"` object of
   `~/.claude/settings.json`, **keeping any hooks already there**. For example,
   alongside an existing `StopFailure` hook:

   ```json
   {
     "hooks": {
       "StopFailure": [ ... existing ... ],
       "PostToolUse": [
         {
           "matcher": "Write|Edit|MultiEdit",
           "hooks": [
             { "type": "command",
               "command": "python3 /path/to/Cortex/hooks/cortex_hook.py",
               "timeout": 15 }
           ]
         }
       ]
     }
   }
   ```

4. Restart Claude Code (or start a new session) so the hook loads.

## How it works

- Reads the hook JSON on stdin, pulls `tool_input.file_path`.
- Walks up from that file to the nearest ancestor directory containing a
  `.cortex/` folder — so only initialised projects are ever touched.
- Runs `cortex sync --changed <file>` for that project (incremental: re-reads
  only the changed file, then re-resolves and re-ranks).

## Other agents

Agents that can't run hooks should follow each project's `CORTEX.md`: run
`cortex sync` after creating or editing files. Same effect, done by convention
instead of automatically.
