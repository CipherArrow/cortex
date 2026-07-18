"""Python extractor using the stdlib `ast` module (accurate, no dependencies).

Extracts classes, functions/methods, imports, inheritance and best-effort call
edges. Call edges carry the callee's simple name in `raw`; graph.resolve() keeps
only those that match a unique internal symbol, which keeps the graph clean.
"""

from __future__ import annotations

import ast

from ..model import (CALLS, CLASS, CONTAINS, DEFINES, FUNCTION, IMPORTS,
                     INHERITS, METHOD, Edge, Node, node_id)
from .base import Extractor


def _docline(node) -> str:
    doc = ast.get_docstring(node)
    if not doc or not doc.strip():
        return ""
    return doc.strip().splitlines()[0][:200]


def _base_name(node) -> str:
    """Best-effort simple name for a base class or call target."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


class _Visitor(ast.NodeVisitor):
    def __init__(self, rel_path: str, file_id: str):
        self.rel = rel_path
        self.file_id = file_id
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self.scope: list[str] = []            # qualname parts
        # Stack of (owner_id, owner_kind); the file counts as owner "module".
        self.owners: list[tuple[str, str]] = [(file_id, "module")]

    def _add_def(self, node, kind: str) -> str:
        qual = ".".join(self.scope + [node.name])
        nid = node_id(self.rel, qual)
        owner_id, owner_kind = self.owners[-1]
        self.nodes.append(Node(
            id=nid, kind=kind, name=node.name, path=self.rel,
            line=getattr(node, "lineno", 0), qualname=qual, lang="python",
            summary=_docline(node),
        ))
        rel_kind = DEFINES if owner_kind == "module" else CONTAINS
        self.edges.append(Edge(src=owner_id, dst=nid, kind=rel_kind))
        return nid

    def visit_ClassDef(self, node: ast.ClassDef):
        nid = self._add_def(node, CLASS)
        for base in node.bases:
            name = _base_name(base)
            if name:
                self.edges.append(Edge(src=nid, dst="", kind=INHERITS, raw=name))
        self.scope.append(node.name)
        self.owners.append((nid, CLASS))
        self.generic_visit(node)
        self.owners.pop()
        self.scope.pop()

    def _visit_func(self, node):
        kind = METHOD if self.owners[-1][1] == CLASS else FUNCTION
        nid = self._add_def(node, kind)
        self.scope.append(node.name)
        self.owners.append((nid, kind))
        self.generic_visit(node)
        self.owners.pop()
        self.scope.pop()

    visit_FunctionDef = _visit_func
    visit_AsyncFunctionDef = _visit_func

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.edges.append(Edge(src=self.file_id, dst="", kind=IMPORTS, raw=alias.name))

    def visit_ImportFrom(self, node: ast.ImportFrom):
        target = ("." * (node.level or 0)) + (node.module or "")
        if target:
            self.edges.append(Edge(src=self.file_id, dst="", kind=IMPORTS, raw=target))

    def visit_Call(self, node: ast.Call):
        # Only attribute-free direct calls (`helper()`), not `obj.method()`.
        # Method calls resolve by bare name and produce false positives
        # (every `path.resolve()` would look like a call to our Graph.resolve).
        if isinstance(node.func, ast.Name):
            self.edges.append(
                Edge(src=self.owners[-1][0], dst="", kind=CALLS, raw=node.func.id))
        self.generic_visit(node)


class PythonExtractor(Extractor):
    key = "python"

    def extract(self, rel_path: str, text: str, file_id: str, lang: str):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return [], []  # unparseable: file still exists as a module node
        v = _Visitor(rel_path, file_id)
        v.visit(tree)
        return v.nodes, v.edges

    def module_summary(self, text: str) -> str:
        try:
            return _docline(ast.parse(text))
        except SyntaxError:
            return ""
