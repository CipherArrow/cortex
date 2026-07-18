"""Language-agnostic extractor for non-Python source, using regexes.

This is deliberately best-effort: it finds top-level definitions and import
statements for a range of languages without needing a parser or grammar files.
It is the pragmatic fallback until/unless tree-sitter is available; the graph
model is identical, so a tree-sitter extractor could drop in later.
"""

from __future__ import annotations

import re

from ..model import (CLASS, DEFINES, FUNCTION, IMPORTS, Edge, Node, node_id)
from .base import Extractor, line_of

# Per-language (compiled_pattern, node_kind, capture_group) definition rules.
# Each pattern's named/numbered group `n` holds the symbol name.
_DEF_RULES: dict[str, list[tuple[re.Pattern, str]]] = {
    "javascript": [
        (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?function\*?\s+([A-Za-z_$][\w$]*)", re.M), FUNCTION),
        (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)", re.M), CLASS),
        (re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", re.M), FUNCTION),
    ],
    "rust": [
        (re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)", re.M), FUNCTION),
        (re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?struct\s+([A-Za-z_]\w*)", re.M), CLASS),
        (re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?enum\s+([A-Za-z_]\w*)", re.M), CLASS),
        (re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?trait\s+([A-Za-z_]\w*)", re.M), CLASS),
    ],
    "go": [
        (re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)", re.M), FUNCTION),
        (re.compile(r"^\s*type\s+([A-Za-z_]\w*)\s+(?:struct|interface)\b", re.M), CLASS),
    ],
    "java": [
        (re.compile(r"^\s*(?:public|private|protected|abstract|final|static|\s)*class\s+([A-Za-z_]\w*)", re.M), CLASS),
        (re.compile(r"^\s*(?:public|private|protected|\s)*interface\s+([A-Za-z_]\w*)", re.M), CLASS),
        (re.compile(r"^\s*(?:public|private|protected|abstract|final|static|synchronized|\s)+[\w<>\[\]]+\s+([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{", re.M), FUNCTION),
    ],
    "c": [
        (re.compile(r"^\s*(?:struct|union|enum)\s+([A-Za-z_]\w*)", re.M), CLASS),
        (re.compile(r"^[A-Za-z_][\w\s\*]+?\b([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{", re.M), FUNCTION),
    ],
    "ruby": [
        (re.compile(r"^\s*def\s+([A-Za-z_]\w*[?!=]?)", re.M), FUNCTION),
        (re.compile(r"^\s*(?:class|module)\s+([A-Za-z_]\w*)", re.M), CLASS),
    ],
    "shell": [
        (re.compile(r"^\s*(?:function\s+)?([A-Za-z_]\w*)\s*\(\)\s*\{", re.M), FUNCTION),
    ],
}
# Aliases share rule sets.
_DEF_RULES["typescript"] = _DEF_RULES["javascript"]
_DEF_RULES["svelte"] = _DEF_RULES["javascript"]
_DEF_RULES["vue"] = _DEF_RULES["javascript"]
_DEF_RULES["cpp"] = _DEF_RULES["c"]
_DEF_RULES["csharp"] = _DEF_RULES["java"]
_DEF_RULES["kotlin"] = _DEF_RULES["java"]
_DEF_RULES["php"] = _DEF_RULES["ruby"]

# Import-statement rules: group holds the imported module/path string.
_IMPORT_RULES: dict[str, list[re.Pattern]] = {
    "javascript": [
        re.compile(r"""^\s*import\s+[^'"]*from\s*['"]([^'"]+)['"]""", re.M),
        re.compile(r"""^\s*import\s*['"]([^'"]+)['"]""", re.M),
        re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)"""),
    ],
    "rust": [re.compile(r"^\s*use\s+([A-Za-z_][\w:]*)", re.M)],
    "go": [re.compile(r"""['"]([\w./-]+)['"]""")],  # applied only within import blocks below
    "java": [re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", re.M)],
    "c": [re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.M)],
    "ruby": [re.compile(r"""^\s*require(?:_relative)?\s+['"]([^'"]+)['"]""", re.M)],
}
_IMPORT_RULES["typescript"] = _IMPORT_RULES["javascript"]
_IMPORT_RULES["svelte"] = _IMPORT_RULES["javascript"]
_IMPORT_RULES["vue"] = _IMPORT_RULES["javascript"]
_IMPORT_RULES["cpp"] = _IMPORT_RULES["c"]

_SVELTE_SCRIPT = re.compile(r"<script[^>]*>(.*?)</script>", re.S | re.I)
_GO_IMPORT_BLOCK = re.compile(r"import\s*\((.*?)\)", re.S)


_MAX_LINE = 10000  # source lines are short; cap so no crafted mega-line can
                   # stress a regex (defense in depth — line numbers are preserved
                   # because the newline count is unchanged).


def _cap_lines(text: str) -> str:
    if len(text) < _MAX_LINE or all(len(ln) <= _MAX_LINE for ln in text.split("\n")):
        return text
    return "\n".join(ln[:_MAX_LINE] for ln in text.split("\n"))


def _script_text(text: str, lang: str) -> str:
    """For component files, narrow to the <script> region for def scanning."""
    if lang in ("svelte", "vue"):
        blocks = _SVELTE_SCRIPT.findall(text)
        if blocks:
            return "\n".join(blocks)
    return text


class RegexExtractor(Extractor):
    key = "regex"

    def extract(self, rel_path: str, text: str, file_id: str, lang: str):
        nodes: list[Node] = []
        edges: list[Edge] = []
        seen: set[str] = set()

        text = _cap_lines(text)
        scan_text = _script_text(text, lang)
        for pattern, kind in _DEF_RULES.get(lang, ()):  # definitions
            for m in pattern.finditer(scan_text):
                name = m.group(1)
                if not name or name in ("if", "for", "while", "switch", "return", "catch"):
                    continue
                qual = name
                nid = node_id(rel_path, qual)
                if nid in seen:
                    continue
                seen.add(nid)
                nodes.append(Node(
                    id=nid, kind=kind, name=name, path=rel_path,
                    line=line_of(scan_text, m.start()), qualname=qual, lang=lang,
                ))
                edges.append(Edge(src=file_id, dst=nid, kind=DEFINES))

        edges.extend(self._imports(rel_path, text, file_id, lang))
        return nodes, edges

    def _imports(self, rel_path: str, text: str, file_id: str, lang: str):
        out: list[Edge] = []
        found: set[str] = set()
        if lang == "go":
            for block in _GO_IMPORT_BLOCK.findall(text):
                for m in _IMPORT_RULES["go"][0].finditer(block):
                    found.add(m.group(1))
            for m in re.finditer(r"""^\s*import\s+['"]([\w./-]+)['"]""", text, re.M):
                found.add(m.group(1))
        else:
            for pattern in _IMPORT_RULES.get(lang, ()):
                for m in pattern.finditer(text):
                    found.add(m.group(1))
        for target in found:
            out.append(Edge(src=file_id, dst="", kind=IMPORTS, raw=target))
        return out
