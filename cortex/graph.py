"""In-memory graph: accumulate nodes/edges, resolve cross-references, rank.

Resolution turns the `raw` targets recorded by extractors (module strings,
wikilinks, callee names) into real edges pointing at internal nodes — or at
`external`/`concept` placeholder nodes when they point outside the project.
Importance is then scored with a small pure-Python PageRank so the map can
surface the true "hub" files and symbols.
"""

from __future__ import annotations

import posixpath
from collections import defaultdict

from .model import (CALLS, CLASS, CONCEPT, DEPENDENCY_KINDS, EXTERNAL, FILE,
                    IMPORTS, INHERITS, LINKS_TO, MODULE, REFERENCES, Edge, Node,
                    node_id)

_PY_EXTS = (".py",)
_JS_EXTS = (".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs", ".svelte", ".vue")


class Graph:
    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []

    # -- construction -----------------------------------------------------
    def add_node(self, node: Node) -> None:
        existing = self.nodes.get(node.id)
        if existing is None:
            self.nodes[node.id] = node
        else:
            # Prefer the richer record (keep summaries / line info if the new
            # one lacks them). Same id == same logical node.
            if not existing.summary and node.summary:
                existing.summary = node.summary
            if not existing.line and node.line:
                existing.line = node.line

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    # -- external / concept placeholders ----------------------------------
    def _external(self, name: str) -> str:
        nid = node_id("", f"ext:{name}")
        if nid not in self.nodes:
            self.nodes[nid] = Node(id=nid, kind=EXTERNAL, name=name, qualname=f"ext:{name}")
        return nid

    def _concept(self, name: str) -> str:
        nid = node_id("", f"concept:{name}")
        if nid not in self.nodes:
            self.nodes[nid] = Node(id=nid, kind=CONCEPT, name=name, qualname=f"concept:{name}")
        return nid

    # -- resolution -------------------------------------------------------
    def resolve(self) -> None:
        by_path = {n.path: n.id for n in self.nodes.values()
                   if n.kind in (FILE, MODULE) and n.path}
        by_stem = defaultdict(list)   # basename-without-ext -> [file id]
        for n in self.nodes.values():
            if n.kind in (FILE, MODULE) and n.path:
                stem = posixpath.splitext(posixpath.basename(n.path))[0]
                by_stem[stem.lower()].append(n.id)
        sym_by_name = defaultdict(list)
        for n in self.nodes.values():
            if n.kind in ("function", "method", "class"):
                sym_by_name[n.name].append(n.id)
        file_of = {n.id: n.path for n in self.nodes.values()}

        resolved: list[Edge] = []
        for e in self.edges:
            if e.dst:                       # already a structural/internal edge
                resolved.append(e)
                continue
            dst = self._resolve_one(e, by_path, by_stem, sym_by_name, file_of)
            if dst:
                e.dst = dst
                resolved.append(e)
            # edges we cannot/shouldn't resolve (e.g. ambiguous calls) are dropped

        # Deduplicate and drop self-loops and edges to missing nodes.
        seen = set()
        clean: list[Edge] = []
        for e in resolved:
            if e.src == e.dst:
                continue
            if e.src not in self.nodes or e.dst not in self.nodes:
                continue
            k = e.key()
            if k in seen:
                continue
            seen.add(k)
            clean.append(e)
        self.edges = clean

    def _resolve_one(self, e, by_path, by_stem, sym_by_name, file_of):
        raw = e.raw.strip()
        if not raw:
            return ""
        if e.kind == IMPORTS:
            src_path = file_of.get(e.src, "")
            hit = _resolve_import(raw, src_path, by_path, by_stem)
            return hit or self._external(_top_pkg(raw))
        if e.kind == INHERITS:
            cands = [i for i in sym_by_name.get(raw, [])
                     if self.nodes[i].kind == CLASS]
            return cands[0] if len(cands) >= 1 else self._external(raw)
        if e.kind == CALLS:
            cands = sym_by_name.get(raw, [])
            if not cands:
                return ""                    # unknown callee: drop
            same = [i for i in cands if file_of.get(i) == file_of.get(e.src)]
            if len(same) == 1:
                return same[0]
            if len(cands) == 1:
                return cands[0]
            return ""                        # ambiguous: drop to avoid noise
        if e.kind == LINKS_TO:
            src_path = file_of.get(e.src, "")
            target = posixpath.normpath(posixpath.join(posixpath.dirname(src_path), raw))
            if target in by_path:
                return by_path[target]
            stem = posixpath.splitext(posixpath.basename(target))[0].lower()
            cands = by_stem.get(stem, [])
            return cands[0] if len(cands) == 1 else ""
        if e.kind == REFERENCES:            # wikilink
            cands = by_stem.get(raw.lower(), [])
            if len(cands) == 1:
                return cands[0]
            return self._concept(raw)        # unresolved wikilink -> concept
        return ""

    # -- ranking ----------------------------------------------------------
    def pagerank(self, damping: float = 0.85, iterations: int = 40) -> None:
        ids = list(self.nodes)
        n = len(ids)
        if n == 0:
            return
        idx = {nid: i for i, nid in enumerate(ids)}
        out = defaultdict(list)
        outdeg = defaultdict(int)
        for e in self.edges:
            if e.kind in DEPENDENCY_KINDS:
                out[e.src].append(e.dst)
                outdeg[e.src] += 1
        rank = [1.0 / n] * n
        base = (1.0 - damping) / n
        for _ in range(iterations):
            nxt = [base] * n
            dangling = 0.0
            for nid in ids:
                if outdeg[nid] == 0:
                    dangling += rank[idx[nid]]
            dangling *= damping / n
            for nid in ids:
                share = rank[idx[nid]]
                deg = outdeg[nid]
                if deg:
                    contrib = damping * share / deg
                    for dst in out[nid]:
                        nxt[idx[dst]] += contrib
            nxt = [v + dangling for v in nxt]
            rank = nxt
        top = max(rank) or 1.0
        for nid in ids:
            self.nodes[nid].rank = round(rank[idx[nid]] / top, 5)

    # -- stats ------------------------------------------------------------
    def stats(self) -> dict:
        kinds = defaultdict(int)
        for n in self.nodes.values():
            kinds[n.kind] += 1
        ekinds = defaultdict(int)
        for e in self.edges:
            ekinds[e.kind] += 1
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "node_kinds": dict(sorted(kinds.items())),
            "edge_kinds": dict(sorted(ekinds.items())),
        }


def _top_pkg(raw: str) -> str:
    raw = raw.lstrip(".")
    for sep in (".", "/", "::"):
        if sep in raw:
            return raw.split(sep)[0]
    return raw or "unknown"


def _resolve_import(raw: str, src_path: str, by_path: dict, by_stem: dict) -> str:
    """Try to map an import string to an internal file id. Returns '' if external."""
    # JS/TS relative import (has a slash: "./lib", "../x/y"). Checked first so
    # it isn't mistaken for a Python dotted relative import.
    if raw.startswith(("./", "../")):
        rel = posixpath.normpath(posixpath.join(posixpath.dirname(src_path), raw))
        return _match_js(rel, by_path)

    # Python relative import: leading dot(s) then a dotted module, no slash.
    if raw.startswith("."):
        dots = len(raw) - len(raw.lstrip("."))
        mod = raw[dots:]
        base = posixpath.dirname(src_path)
        for _ in range(dots - 1):
            base = posixpath.dirname(base)
        rel = posixpath.join(base, mod.replace(".", "/")) if mod else base
        return _match_py(rel, by_path)

    # Python absolute dotted module.
    if src_path.endswith(".py") or ("." in raw and "/" not in raw):
        hit = _match_py(raw.replace(".", "/"), by_path)
        if hit:
            return hit

    # Rust: crate::a::b or a::b -> src/a/b.rs or a/b.rs
    if "::" in raw:
        parts = [p for p in raw.split("::") if p not in ("crate", "self", "super")]
        cand = "/".join(parts)
        for pre in ("src/", ""):
            for ext in (".rs",):
                p = f"{pre}{cand}{ext}"
                if p in by_path:
                    return by_path[p]

    # Generic last-resort: a dotted/pathy import whose final segment uniquely
    # matches one internal file stem (handles Java/Kotlin/etc. cleanly).
    for seg in reversed([s for s in raw.replace("::", ".").replace("/", ".").split(".") if s]):
        cands = by_stem.get(seg.lower(), [])
        if len(cands) == 1:
            return cands[0]
        if cands:
            break  # ambiguous stem: don't guess
    return ""


def _match_py(rel: str, by_path: dict) -> str:
    rel = rel.strip("/")
    for cand in (f"{rel}.py", f"{rel}/__init__.py", f"{rel}.pyi"):
        if cand in by_path:
            return by_path[cand]
    # Try matching just the tail (e.g. import maps to a nested package root).
    tail = rel.split("/")[-1]
    for path, nid in by_path.items():
        if path.endswith(f"/{tail}.py") or path == f"{tail}.py":
            return nid
    return ""


def _match_js(rel: str, by_path: dict) -> str:
    rel = rel.strip("/")
    for ext in _JS_EXTS:
        if f"{rel}{ext}" in by_path:
            return by_path[f"{rel}{ext}"]
    for ext in _JS_EXTS:
        if f"{rel}/index{ext}" in by_path:
            return by_path[f"{rel}/index{ext}"]
    if rel in by_path:
        return by_path[rel]
    return ""
