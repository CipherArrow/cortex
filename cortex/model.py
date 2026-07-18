"""Graph data model: Node and Edge, plus stable id helpers.

Node/Edge kinds are plain string constants (not enums) so they serialise to
JSON and SQLite with zero ceremony. IDs are deterministic sha1 slugs of the
path + qualified name, so re-scanning a file produces the *same* ids and
incremental updates diff cleanly.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

# --- Node kinds --------------------------------------------------------------
DIR = "dir"
FILE = "file"
MODULE = "module"          # a source file that defines a namespace (e.g. .py)
CLASS = "class"
FUNCTION = "function"
METHOD = "method"
HEADING = "heading"        # a markdown section
CONCEPT = "concept"        # a wikilink target or #tag with no backing file
CONFIG_KEY = "config_key"  # a top-level key in yaml/toml config
EXTERNAL = "external"      # a third-party / unresolved import target

# --- Edge kinds --------------------------------------------------------------
CONTAINS = "contains"      # dir->file, file->symbol, class->method (structural)
IMPORTS = "imports"        # file depends on another module/file
CALLS = "calls"            # symbol invokes another symbol
REFERENCES = "references"  # wikilink / prose mention
LINKS_TO = "links_to"      # markdown [text](path) link
DEFINES = "defines"        # file defines a top-level symbol
INHERITS = "inherits"      # class subclasses another class
TAGGED = "tagged"          # doc carries a #tag concept

# Edge kinds that express *dependency* (used for PageRank importance). Purely
# structural edges (CONTAINS, DEFINES) are excluded so the ranking reflects
# what code/docs actually lean on, not the folder tree.
DEPENDENCY_KINDS = frozenset({IMPORTS, CALLS, REFERENCES, LINKS_TO, INHERITS})


def node_id(path: str, qualname: str = "") -> str:
    """Deterministic short id for a node.

    `path` is the repo-relative path (or "" for a pure concept); `qualname` is
    the dotted name within the file (or a "concept:"/"tag:" prefix for
    file-less nodes).
    """
    raw = f"{path}::{qualname}" if qualname else path
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:12]


@dataclass
class Node:
    id: str
    kind: str
    name: str            # short display name
    path: str = ""       # repo-relative file (or dir) path; "" for concepts
    line: int = 0        # 1-based definition line
    qualname: str = ""   # dotted name within the file
    lang: str = ""
    summary: str = ""    # one-line: docstring/heading/first-line
    loc: int = 0         # lines of code (files only)
    rank: float = 0.0    # PageRank importance, filled at build time

    def __post_init__(self):
        # Summaries come from untrusted scanned content (docstrings, headings),
        # then flow into MAP.md and the graph viewer. Neutralise them at the one
        # place every node passes through. Names are identifiers; just bound them.
        from .secure import clean_text
        if self.summary:
            self.summary = clean_text(self.summary, 200)
        if self.name:
            self.name = clean_text(self.name, 160)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Node":
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


@dataclass
class Edge:
    src: str             # source node id
    dst: str             # destination node id (may be a placeholder pre-resolve)
    kind: str
    raw: str = ""        # unresolved target text (module string, wikilink, ...)

    def key(self) -> tuple:
        return (self.src, self.dst, self.kind)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Edge":
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})
