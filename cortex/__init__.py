"""Cortex — a self-updating project knowledge graph for AI agents.

Cortex scans a project into a graph of files, symbols, docs and links, then
persists it as both AI-readable Markdown and a queryable SQLite index so any
agent (or local LLM) can look things up instead of re-reading the whole tree.

Zero third-party dependencies: standard library only.
"""

__version__ = "0.2.0"

# --- Naming (centralised so the tool is trivial to rename) -------------------
# The user-facing name of the tool and its CLI command. To rebrand, change
# these two strings and the `bin/` shim name; the Python package can stay
# `cortex` internally.
TOOL_NAME = "Cortex"
CLI_NAME = "cortex"

# The per-project data directory (created inside each scanned project, like .git).
DATA_DIR = ".cortex"

# Files written inside a scanned project's DATA_DIR.
GRAPH_FILE = "graph.json"
INDEX_FILE = "index.db"
MANIFEST_FILE = "manifest.json"
CONFIG_FILE = "config.toml"
MAP_FILE = "MAP.md"

# The single visible pointer dropped at a scanned project's root.
POINTER_FILE = "CORTEX.md"
