# Cortex auto-sync hook (Claude Code)

This keeps every Cortex-mapped project fresh automatically: after Claude Code
writes or edits a file, the hook runs an incremental `cortex sync` for the
project that owns that file. It is a silent no-op for files outside a Cortex
project, and it never blocks work (any error → exit 0).

## Install

1. Make the hook script executable (from this repo's root):
   ```bash
   chmod +x hooks/cortex_hook.py
   ```

2. Get the exact settings block — `install-hook` fills in the absolute paths
   for your machine automatically:
   ```bash
   cortex install-hook
   ```

3. Merge the printed `PostToolUse` entry into the `"hooks"` object of
   `~/.claude/settings.json`, **keeping any hooks already there**. The shape
   (with `<CORTEX>` standing for wherever you cloned this repo):

   ```json
   {
     "hooks": {
       "PostToolUse": [
         {
           "matcher": "Write|Edit|MultiEdit|NotebookEdit",
           "hooks": [
             { "type": "command",
               "command": "python3 <CORTEX>/hooks/cortex_hook.py",
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
