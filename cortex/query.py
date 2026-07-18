"""Query engine over the SQLite index — the token-saving lookup layer.

Every function returns compact, ready-to-read text so an agent can paste the
result straight into its reasoning instead of opening source files.
"""

from __future__ import annotations

import sqlite3

from .activity import log_touch
from .config import Config
from .store import connect

_FTS_SPECIAL = set('"*():^')


def _fts_query(term: str) -> str:
    """Turn a free-text term into a safe FTS5 prefix query."""
    tokens = []
    for word in term.replace(":", " ").split():
        word = "".join(c for c in word if c not in _FTS_SPECIAL)
        if word:
            tokens.append(f'{word}*')
    return " ".join(tokens)


def search(cfg: Config, term: str, kind: str | None = None, limit: int = 20):
    con = connect(cfg)
    if con is None:
        return None
    try:
        fts = _fts_query(term)
        rows = []
        if fts:
            sql = (
                "SELECT n.* FROM search s JOIN nodes n ON n.id = s.id "
                "WHERE search MATCH ? "
            )
            params = [fts]
            if kind:
                sql += "AND n.kind = ? "
                params.append(kind)
            sql += "ORDER BY n.rank DESC, n.loc DESC LIMIT ?"
            params.append(limit)
            try:
                rows = con.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                rows = []
        if not rows:  # fallback: LIKE on name/qualname/summary
            like = f"%{term}%"
            sql = ("SELECT * FROM nodes WHERE (name LIKE ? OR qualname LIKE ? "
                   "OR summary LIKE ?) ")
            params = [like, like, like]
            if kind:
                sql += "AND kind = ? "
                params.append(kind)
            sql += "ORDER BY rank DESC LIMIT ?"
            params.append(limit)
            rows = con.execute(sql, params).fetchall()
        out = [dict(r) for r in rows]
        log_touch(cfg, "query", [r["id"] for r in out])
        return out
    finally:
        con.close()


def _find_node(con, ref: str):
    """Resolve a node reference: id, exact path, or symbol name."""
    r = con.execute("SELECT * FROM nodes WHERE id = ?", (ref,)).fetchone()
    if r:
        return dict(r)
    # A path matches both the file node and its headings/symbols; prefer the file.
    r = con.execute(
        "SELECT * FROM nodes WHERE path = ? "
        "ORDER BY CASE WHEN kind IN ('file','module') THEN 0 ELSE 1 END, rank DESC "
        "LIMIT 1", (ref,)).fetchone()
    if r:
        return dict(r)
    r = con.execute(
        "SELECT * FROM nodes WHERE name = ? OR qualname = ? ORDER BY rank DESC LIMIT 1",
        (ref, ref)).fetchone()
    return dict(r) if r else None


def neighbors(cfg: Config, ref: str):
    con = connect(cfg)
    if con is None:
        return None
    try:
        node = _find_node(con, ref)
        if not node:
            return {"error": f"no node matching '{ref}'"}
        # Alias the edge kind so it doesn't collide with the node's own `kind`.
        out = con.execute(
            "SELECT e.kind AS edge, n.* FROM edges e JOIN nodes n ON n.id = e.dst "
            "WHERE e.src = ?", (node["id"],)).fetchall()
        inc = con.execute(
            "SELECT e.kind AS edge, n.* FROM edges e JOIN nodes n ON n.id = e.src "
            "WHERE e.dst = ?", (node["id"],)).fetchall()
        res = {"node": node,
               "outgoing": [dict(r) for r in out],
               "incoming": [dict(r) for r in inc]}
        log_touch(cfg, "neighbors",
                  [node["id"]] + [r["id"] for r in res["outgoing"] + res["incoming"]])
        return res
    finally:
        con.close()


def context(cfg: Config, ref: str):
    """A compact 'context pack' for a symbol: definition + callers/callees/siblings."""
    con = connect(cfg)
    if con is None:
        return None
    try:
        node = _find_node(con, ref)
        if not node:
            return {"error": f"no node matching '{ref}'"}
        nid = node["id"]
        callers = con.execute(
            "SELECT n.* FROM edges e JOIN nodes n ON n.id = e.src "
            "WHERE e.dst = ? AND e.kind = 'calls'", (nid,)).fetchall()
        callees = con.execute(
            "SELECT n.* FROM edges e JOIN nodes n ON n.id = e.dst "
            "WHERE e.src = ? AND e.kind = 'calls'", (nid,)).fetchall()
        siblings = []
        if node["path"]:
            siblings = con.execute(
                "SELECT * FROM nodes WHERE path = ? AND kind IN "
                "('function','method','class') AND id != ? ORDER BY line LIMIT 20",
                (node["path"], nid)).fetchall()
        importers = con.execute(
            "SELECT n.* FROM edges e JOIN nodes n ON n.id = e.src "
            "WHERE e.dst = ? AND e.kind IN ('imports','references','links_to')",
            (nid,)).fetchall()
        res = {
            "node": node,
            "callers": [dict(r) for r in callers],
            "callees": [dict(r) for r in callees],
            "siblings": [dict(r) for r in siblings],
            "importers": [dict(r) for r in importers],
        }
        log_touch(cfg, "context", [node["id"]] +
                  [r["id"] for k in ("callers", "callees", "siblings", "importers")
                   for r in res[k]])
        return res
    finally:
        con.close()


def hubs(cfg: Config, limit: int = 20, kind: str | None = None):
    con = connect(cfg)
    if con is None:
        return None
    try:
        sql = "SELECT * FROM nodes WHERE rank > 0 "
        params = []
        if kind:
            sql += "AND kind = ? "
            params.append(kind)
        else:  # default: real navigable nodes, not placeholders/folders
            sql += "AND kind NOT IN ('external','concept','dir') "
        sql += "ORDER BY rank DESC LIMIT ?"
        params.append(limit)
        out = [dict(r) for r in con.execute(sql, params).fetchall()]
        log_touch(cfg, "hubs", [r["id"] for r in out])
        return out
    finally:
        con.close()


def get_stats(cfg: Config):
    con = connect(cfg)
    if con is None:
        return None
    try:
        import json as _json
        r = con.execute("SELECT value FROM meta WHERE key='stats'").fetchone()
        gen = con.execute("SELECT value FROM meta WHERE key='generated_at'").fetchone()
        stats = _json.loads(r["value"]) if r else {}
        stats["generated_at"] = int(gen["value"]) if gen else 0
        return stats
    finally:
        con.close()
