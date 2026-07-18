"""Export the dependency graph as Mermaid or Graphviz DOT for visualization.

Only file-level dependency edges are drawn, capped to the top-ranked nodes, so
the diagram stays legible (the full graph lives in graph.json / the index).
"""

from __future__ import annotations

from .graph import Graph
from .model import DEPENDENCY_KINDS, FILE, MODULE


def _top_files(graph: Graph, limit: int):
    files = [n for n in graph.nodes.values() if n.kind in (FILE, MODULE) and n.path]
    files.sort(key=lambda n: n.rank, reverse=True)
    return files[:limit]


def _file_edges(graph: Graph, keep: set):
    seen = set()
    for e in graph.edges:
        if e.kind not in DEPENDENCY_KINDS:
            continue
        if e.src in keep and e.dst in keep and e.src != e.dst:
            k = (e.src, e.dst)
            if k not in seen:
                seen.add(k)
                yield e


def to_mermaid(graph: Graph, limit: int = 60) -> str:
    files = _top_files(graph, limit)
    keep = {n.id for n in files}
    label = {n.id: n.path for n in files}
    lines = ["```mermaid", "graph LR"]
    for n in files:
        safe = n.path.replace('"', "'")
        lines.append(f'  {n.id}["{safe}"]')
    for e in _file_edges(graph, keep):
        lines.append(f"  {e.src} --> {e.dst}")
    lines.append("```")
    return "\n".join(lines)


def to_dot(graph: Graph, limit: int = 100) -> str:
    files = _top_files(graph, limit)
    keep = {n.id for n in files}
    lines = ["digraph cortex {", '  rankdir=LR;', '  node [shape=box, fontsize=10];']
    for n in files:
        safe = n.path.replace('"', "'")
        lines.append(f'  "{n.id}" [label="{safe}"];')
    for e in _file_edges(graph, keep):
        lines.append(f'  "{e.src}" -> "{e.dst}";')
    lines.append("}")
    return "\n".join(lines)
