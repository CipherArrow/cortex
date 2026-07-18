"""Scan orchestration: walk -> extract -> graph -> resolve -> rank -> persist.

`full_scan` rebuilds everything. `sync` re-extracts only the files whose content
hash changed (or a caller-supplied list), then re-resolves and re-ranks the whole
graph so cross-file edges stay correct.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import DATA_DIR, POINTER_FILE
from .config import EXT_LANG, MODULE_LANGS, Config, load_config
from .emit_markdown import write_map, write_pointer
from .extractors import get_extractor
from .extractors.markdown import MarkdownExtractor
from .extractors.python_ast import PythonExtractor
from .graph import Graph
from .model import CONTAINS, DIR, FILE, MODULE, Edge, Node, node_id
from .store import load_graph, save_graph
from .walker import (diff_manifest, file_hash, iter_files, load_manifest,
                     save_manifest)

_MD = MarkdownExtractor()
_PY = PythonExtractor()


def _read(path: Path) -> str:
    try:
        return path.read_text("utf-8", errors="replace")
    except OSError:
        return ""


def _file_summary(lang: str, text: str) -> str:
    if lang == "python":
        return _PY.module_summary(text)
    if lang == "markdown":
        return _MD.title(text)
    return ""


def _add_file(graph: Graph, rel: str, text: str) -> None:
    """Add one file's node + its extracted symbols/edges to the graph."""
    ext = Path(rel).suffix.lower()
    lang, extractor_key = EXT_LANG.get(ext, ("", ""))
    kind = MODULE if lang in MODULE_LANGS else FILE
    fid = node_id(rel)
    loc = text.count("\n") + 1 if text else 0
    graph.add_node(Node(id=fid, kind=kind, name=Path(rel).name, path=rel,
                        lang=lang, loc=loc, summary=_file_summary(lang, text)))
    extractor = get_extractor(extractor_key)
    if extractor:
        nodes, edges = extractor.extract(rel, text, fid, lang)
        for n in nodes:
            graph.add_node(n)
        for e in edges:
            graph.add_edge(e)


def _add_dirs(graph: Graph, rel_paths) -> None:
    """Add directory nodes and structural contains edges (dir->child)."""
    dirs: set[str] = set()
    for rel in rel_paths:
        parts = rel.split("/")[:-1]
        for i in range(len(parts)):
            dirs.add("/".join(parts[: i + 1]))
    for d in dirs:
        graph.add_node(Node(id=node_id(d), kind=DIR, name=d.split("/")[-1], path=d))
    # dir -> subdir / dir -> file
    for rel in rel_paths:
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        if parent:
            graph.add_edge(Edge(src=node_id(parent), dst=node_id(rel), kind=CONTAINS))
    for d in dirs:
        if "/" in d:
            parent = d.rsplit("/", 1)[0]
            graph.add_edge(Edge(src=node_id(parent), dst=node_id(d), kind=CONTAINS))


def _finalize(cfg: Config, graph: Graph, manifest: dict) -> dict:
    graph.resolve()
    graph.pagerank()
    meta = save_graph(cfg, graph, extra_meta={"files": len(manifest)})
    save_manifest(cfg, manifest)
    write_map(cfg, graph)
    write_pointer(cfg)
    return meta


def full_scan(root: str | Path) -> dict:
    cfg = load_config(root)
    from .lockfile import project_lock
    with project_lock(cfg):
        return _full_scan_locked(cfg)


def _full_scan_locked(cfg: Config) -> dict:
    graph = Graph()
    manifest: dict = {}
    rel_paths: list[str] = []
    for abs_path, rel in iter_files(cfg):
        text = _read(abs_path)
        _add_file(graph, rel, text)
        rel_paths.append(rel)
        try:
            st = abs_path.stat()
            manifest[rel] = {"hash": file_hash(abs_path),
                             "mtime": int(st.st_mtime), "size": st.st_size}
        except OSError:
            pass
    _add_dirs(graph, rel_paths)
    meta = _finalize(cfg, graph, manifest)
    meta["scan"] = "full"
    return meta


def _drop_file(graph: Graph, rel: str) -> None:
    """Remove a file's nodes (file + symbols under it) and their edges."""
    dead = {nid for nid, n in graph.nodes.items() if n.path == rel}
    if not dead:
        dead = {node_id(rel)}
    for nid in dead:
        graph.nodes.pop(nid, None)
    graph.edges = [e for e in graph.edges
                   if e.src not in dead and e.dst not in dead]


def sync(root: str | Path, changed: list[str] | None = None) -> dict:
    cfg = load_config(root)
    from .lockfile import project_lock
    with project_lock(cfg):
        return _sync_locked(cfg, changed)


def _sync_locked(cfg: Config, changed: list[str] | None = None) -> dict:
    graph = load_graph(cfg)
    if graph is None:
        return _full_scan_locked(cfg)

    old_manifest = load_manifest(cfg)
    # Determine what changed. An explicit list (from the hook) still gets
    # validated against disk so deletes/renames are handled.
    from .walker import scan_manifest
    new_manifest = scan_manifest(cfg)
    diff = diff_manifest(old_manifest, new_manifest)

    if changed:
        wanted = {os.path.relpath(Path(c).resolve(), cfg.root).replace(os.sep, "/")
                  if os.path.isabs(c) else c for c in changed}
        touched = [r for r in diff.touched if r in wanted] or [
            r for r in wanted if r in new_manifest]
        removed = [r for r in diff.removed if r in wanted]
    else:
        touched, removed = diff.touched, diff.removed

    if not touched and not removed:
        # Nothing changed; still make sure the pointer exists.
        if not (cfg.root / POINTER_FILE).exists():
            write_pointer(cfg)
        meta = save_graph(cfg, graph)  # refresh index/timestamps cheaply
        meta["scan"] = "noop"
        return meta

    from .secure import within_root
    for rel in set(touched) | set(removed):
        _drop_file(graph, rel)
    for rel in touched:
        abs_path = cfg.root / rel
        # Defense in depth: never read a path that resolves outside the project,
        # even if a caller-supplied --changed entry tried to escape.
        if not within_root(abs_path, cfg.root):
            continue
        _add_file(graph, rel, _read(abs_path))
    _add_dirs(graph, [r for r in new_manifest])

    meta = _finalize(cfg, graph, new_manifest)
    meta["scan"] = "incremental"
    meta["changed"] = {"touched": touched, "removed": removed}
    from .activity import log_touch
    log_touch(cfg, "sync", [node_id(rel) for rel in touched])
    return meta
