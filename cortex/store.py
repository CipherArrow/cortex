"""Persistence: canonical graph.json + a queryable SQLite/FTS5 index.

graph.json is the human/tooling-readable source of truth. index.db is the fast
lookup layer an agent hits with `cortex query` so it never has to load the whole
graph (or the whole codebase) into its context window.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from . import GRAPH_FILE, INDEX_FILE, __version__
from .config import Config
from .graph import Graph
from .model import Edge, Node
from .secure import harden_file, secure_dir


def save_graph(cfg: Config, graph: Graph, extra_meta: dict | None = None) -> dict:
    secure_dir(cfg.data_dir)   # owner-only: keeps the index unreadable to others
    meta = {
        "tool": "cortex",
        "version": __version__,
        "generated_at": int(time.time()),
        "root": str(cfg.root),
        "stats": graph.stats(),
    }
    if extra_meta:
        meta.update(extra_meta)

    payload = {
        "meta": meta,
        "nodes": [n.to_dict() for n in graph.nodes.values()],
        "edges": [e.to_dict() for e in graph.edges],
    }
    # Atomic: write to a temp file, then swap. Concurrent readers always see
    # either the previous complete graph or the new one, never a partial write.
    target = cfg.data_dir / GRAPH_FILE
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), "utf-8")
    harden_file(tmp)
    os.replace(tmp, target)
    harden_file(target)

    _build_index(cfg, graph, meta)
    return meta


def load_graph(cfg: Config) -> Graph | None:
    path = cfg.data_dir / GRAPH_FILE
    if not path.is_file():
        return None
    data = json.loads(path.read_text("utf-8"))
    g = Graph()
    for nd in data["nodes"]:
        n = Node.from_dict(nd)
        g.nodes[n.id] = n
    for ed in data["edges"]:
        g.edges.append(Edge.from_dict(ed))
    return g


def _build_index(cfg: Config, graph: Graph, meta: dict) -> None:
    # Build into a temp db, then atomically swap it in. A reader mid-query on
    # the old file keeps its open inode; new connections get the new index.
    db_path = cfg.data_dir / INDEX_FILE
    tmp_path = cfg.data_dir / (INDEX_FILE + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    con = sqlite3.connect(tmp_path)
    try:
        con.executescript(
            """
            CREATE TABLE nodes(
                id TEXT PRIMARY KEY, kind TEXT, name TEXT, path TEXT,
                line INTEGER, qualname TEXT, lang TEXT, summary TEXT,
                loc INTEGER, rank REAL
            );
            CREATE TABLE edges(src TEXT, dst TEXT, kind TEXT, raw TEXT);
            CREATE INDEX idx_edges_src ON edges(src);
            CREATE INDEX idx_edges_dst ON edges(dst);
            CREATE INDEX idx_nodes_name ON nodes(name);
            CREATE INDEX idx_nodes_path ON nodes(path);
            CREATE INDEX idx_nodes_kind ON nodes(kind);
            CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
            CREATE VIRTUAL TABLE search USING fts5(
                id UNINDEXED, name, qualname, path, kind, summary,
                tokenize = "unicode61"
            );
            """
        )
        con.executemany(
            "INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?,?)",
            [(n.id, n.kind, n.name, n.path, n.line, n.qualname, n.lang,
              n.summary, n.loc, n.rank) for n in graph.nodes.values()],
        )
        con.executemany(
            "INSERT INTO edges VALUES(?,?,?,?)",
            [(e.src, e.dst, e.kind, e.raw) for e in graph.edges],
        )
        con.executemany(
            "INSERT INTO search VALUES(?,?,?,?,?,?)",
            [(n.id, n.name, n.qualname, n.path, n.kind, n.summary)
             for n in graph.nodes.values()],
        )
        con.executemany(
            "INSERT INTO meta VALUES(?,?)",
            [("version", meta["version"]),
             ("generated_at", str(meta["generated_at"])),
             ("root", meta["root"]),
             ("stats", json.dumps(meta["stats"]))],
        )
        con.commit()
    finally:
        con.close()
    harden_file(tmp_path)
    os.replace(tmp_path, db_path)
    harden_file(db_path)


def connect(cfg: Config) -> sqlite3.Connection | None:
    db_path = cfg.data_dir / INDEX_FILE
    if not db_path.is_file():
        return None
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con
