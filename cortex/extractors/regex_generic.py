"""Language-agnostic extractor for non-Python source, using regexes.

This is deliberately best-effort: it finds top-level definitions and import
statements for a range of languages without needing a parser or grammar files.
It is the pragmatic fallback until/unless tree-sitter is available; the graph
model is identical, so a tree-sitter extractor could drop in later.
"""

from __future__ import annotations

import re

from ..model import (CLASS, DEFINES, FUNCTION, IMPORTS, METHOD, Edge, Node,
                     node_id)
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

# --- Tier-2 languages added for broad adopter coverage. Patterns are
# line-anchored and use only bounded/disjoint repetition, so they stay linear
# (ReDoS-safe) and are further bounded by _cap_lines. Group 1 = symbol name. ---
_MOD = r"(?:[\w@]+\s+){0,6}"   # up to 6 leading modifier/keyword words
_DEF_RULES.update({
    "swift": [
        (re.compile(rf"^\s*{_MOD}func\s+([A-Za-z_]\w*)", re.M), FUNCTION),
        (re.compile(rf"^\s*{_MOD}(?:class|struct|enum|protocol|extension|actor)\s+([A-Za-z_]\w*)", re.M), CLASS),
    ],
    "kotlin": [
        (re.compile(rf"^\s*{_MOD}fun\s+([A-Za-z_]\w*)", re.M), FUNCTION),
        (re.compile(rf"^\s*{_MOD}(?:class|interface|object|enum\s+class|data\s+class)\s+([A-Za-z_]\w*)", re.M), CLASS),
    ],
    "csharp": [
        (re.compile(rf"^\s*{_MOD}(?:class|interface|struct|enum|record)\s+([A-Za-z_]\w*)", re.M), CLASS),
        (re.compile(rf"^\s*{_MOD}[\w<>\[\],.]+\s+([A-Za-z_]\w*)\s*\([^;{{]*\)\s*\{{", re.M), FUNCTION),
    ],
    "php": [
        (re.compile(rf"^\s*{_MOD}function\s+&?\s*([A-Za-z_]\w*)", re.M), FUNCTION),
        (re.compile(rf"^\s*{_MOD}(?:class|interface|trait|enum)\s+([A-Za-z_]\w*)", re.M), CLASS),
    ],
    "scala": [
        (re.compile(rf"^\s*{_MOD}def\s+([A-Za-z_]\w*)", re.M), FUNCTION),
        (re.compile(rf"^\s*{_MOD}(?:class|object|trait|case\s+class)\s+([A-Za-z_]\w*)", re.M), CLASS),
    ],
    "dart": [
        (re.compile(r"^\s*(?:class|mixin|enum|extension)\s+([A-Za-z_]\w*)", re.M), CLASS),
        (re.compile(r"^\s*(?:[\w<>,\?]+\s+)?([A-Za-z_]\w*)\s*\([^;{]*\)\s*(?:async\s*)?\{", re.M), FUNCTION),
    ],
    "lua": [
        (re.compile(r"^\s*(?:local\s+)?function\s+([A-Za-z_][\w.:]*)", re.M), FUNCTION),
    ],
    "elixir": [
        (re.compile(r"^\s*def(?:p|macro|macrop)?\s+([A-Za-z_]\w*[!?]?)", re.M), FUNCTION),
        (re.compile(r"^\s*defmodule\s+([A-Za-z_][\w.]*)", re.M), CLASS),
        (re.compile(r"^\s*defprotocol\s+([A-Za-z_][\w.]*)", re.M), CLASS),
    ],
    "erlang": [
        (re.compile(r"^-module\(\s*([a-z_]\w*)", re.M), CLASS),
        (re.compile(r"^([a-z_]\w*)\s*\(", re.M), FUNCTION),
    ],
    "haskell": [
        (re.compile(r"^([a-z_]\w*)\s*::", re.M), FUNCTION),
        (re.compile(r"^\s*(?:data|newtype|type|class)\s+([A-Z]\w*)", re.M), CLASS),
    ],
    "clojure": [
        (re.compile(r"\(defn-?\s+([A-Za-z_][\w!?*+.\/<>=-]*)", re.M), FUNCTION),
        (re.compile(r"\(def(?:macro|method)\s+([A-Za-z_][\w!?*+.\/<>=-]*)", re.M), FUNCTION),
        (re.compile(r"\(defrecord\s+([A-Za-z_]\w*)", re.M), CLASS),
    ],
    "ocaml": [
        (re.compile(r"^\s*let\s+(?:rec\s+)?([a-z_]\w*)", re.M), FUNCTION),
        (re.compile(r"^\s*(?:module|type)\s+([A-Za-z_]\w*)", re.M), CLASS),
    ],
    "fsharp": [
        (re.compile(r"^\s*let\s+(?:rec\s+|inline\s+)*([a-z_]\w*)", re.M), FUNCTION),
        (re.compile(r"^\s*(?:module|type)\s+([A-Za-z_]\w*)", re.M), CLASS),
    ],
    "objc": [
        (re.compile(r"^\s*@(?:interface|implementation|protocol)\s+([A-Za-z_]\w*)", re.M), CLASS),
        (re.compile(r"^\s*[-+]\s*\([\w\s\*]+\)\s*([A-Za-z_]\w*)", re.M), METHOD),
    ],
    "groovy": [
        (re.compile(rf"^\s*{_MOD}def\s+([A-Za-z_]\w*)", re.M), FUNCTION),
        (re.compile(rf"^\s*{_MOD}(?:class|interface|trait|enum)\s+([A-Za-z_]\w*)", re.M), CLASS),
    ],
    "powershell": [
        (re.compile(r"^\s*function\s+([A-Za-z_][\w-]*)", re.M | re.I), FUNCTION),
        (re.compile(r"^\s*class\s+([A-Za-z_]\w*)", re.M), CLASS),
    ],
    "perl": [
        (re.compile(r"^\s*sub\s+([A-Za-z_]\w*)", re.M), FUNCTION),
        (re.compile(r"^\s*package\s+([A-Za-z_][\w:]*)", re.M), CLASS),
    ],
    "r": [
        (re.compile(r"^\s*([A-Za-z.][\w.]*)\s*(?:<-|=)\s*function", re.M), FUNCTION),
    ],
    "julia": [
        (re.compile(r"^\s*(?:function|macro)\s+([A-Za-z_]\w*)", re.M), FUNCTION),
        (re.compile(r"^\s*(?:struct|mutable\s+struct|abstract\s+type|module)\s+([A-Za-z_]\w*)", re.M), CLASS),
    ],
    "zig": [
        (re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)", re.M), FUNCTION),
        (re.compile(r"^\s*(?:pub\s+)?const\s+([A-Za-z_]\w*)\s*=\s*(?:packed\s+|extern\s+)?(?:struct|enum|union|opaque)", re.M), CLASS),
    ],
    "nim": [
        (re.compile(r"^\s*(?:proc|func|method|iterator|template|macro)\s+([A-Za-z_]\w*)", re.M), FUNCTION),
        (re.compile(r"^\s*type\s+([A-Za-z_]\w*)", re.M), CLASS),
    ],
    "solidity": [
        (re.compile(r"^\s*function\s+([A-Za-z_]\w*)", re.M), FUNCTION),
        (re.compile(r"^\s*(?:contract|interface|library|struct|enum)\s+([A-Za-z_]\w*)", re.M), CLASS),
        (re.compile(r"^\s*(?:event|modifier)\s+([A-Za-z_]\w*)", re.M), FUNCTION),
    ],
    "protobuf": [
        (re.compile(r"^\s*(?:message|service|enum)\s+([A-Za-z_]\w*)", re.M), CLASS),
        (re.compile(r"^\s*rpc\s+([A-Za-z_]\w*)", re.M), FUNCTION),
    ],
    "graphql": [
        (re.compile(r"^\s*(?:type|input|interface|enum|union|scalar)\s+([A-Za-z_]\w*)", re.M), CLASS),
    ],
    "sql": [
        (re.compile(r"(?:CREATE|ALTER)\s+(?:TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?([A-Za-z_]\w*)", re.I), CLASS),
        (re.compile(r"(?:CREATE|REPLACE)\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE)\s+[`\"\[]?([A-Za-z_]\w*)", re.I), FUNCTION),
    ],
    "terraform": [
        (re.compile(r'^\s*(?:resource|data)\s+"([A-Za-z_]\w*)"', re.M), CLASS),
        (re.compile(r'^\s*(?:module|variable|output)\s+"([A-Za-z_]\w*)"', re.M), FUNCTION),
    ],
})

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

_IMPORT_RULES.update({
    "kotlin": [re.compile(r"^\s*import\s+([\w.]+)", re.M)],
    "csharp": [re.compile(r"^\s*using\s+(?:static\s+)?([\w.]+)\s*;", re.M)],
    "swift": [re.compile(r"^\s*import\s+([\w.]+)", re.M)],
    "scala": [re.compile(r"^\s*import\s+([\w.]+)", re.M)],
    "groovy": [re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)", re.M)],
    "dart": [re.compile(r"""^\s*(?:import|part|export)\s+['"]([^'"]+)['"]""", re.M)],
    "lua": [re.compile(r"""require\s*\(?\s*['"]([^'"]+)['"]""")],
    "elixir": [re.compile(r"^\s*(?:import|alias|require|use)\s+([A-Za-z_][\w.]*)", re.M)],
    "erlang": [re.compile(r"^-import\(\s*([a-z_]\w*)", re.M)],
    "haskell": [re.compile(r"^\s*import\s+(?:qualified\s+)?([A-Z][\w.]*)", re.M)],
    "clojure": [re.compile(r"\(:require\s+\[?\s*([A-Za-z_][\w.]*)")],
    "ocaml": [re.compile(r"^\s*open\s+([A-Z]\w*)", re.M)],
    "fsharp": [re.compile(r"^\s*open\s+([\w.]+)", re.M)],
    "objc": [re.compile(r'^\s*#\s*import\s*[<"]([^>"]+)[>"]', re.M)],
    "perl": [re.compile(r"^\s*use\s+([A-Za-z_][\w:]*)", re.M)],
    "julia": [re.compile(r"^\s*(?:using|import)\s+([A-Za-z_][\w.]*)", re.M)],
    "nim": [re.compile(r"^\s*import\s+([A-Za-z_][\w./]*)", re.M)],
    "zig": [re.compile(r"""@import\(\s*['"]([^'"]+)['"]""")],
    "solidity": [re.compile(r"""^\s*import\s+[^'"]*['"]([^'"]+)['"]""", re.M)],
    "protobuf": [re.compile(r"""^\s*import\s+(?:public\s+|weak\s+)?['"]([^'"]+)['"]""", re.M)],
    "r": [re.compile(r"""(?:library|require)\(\s*['"]?([A-Za-z_][\w.]*)""")],
    "php": [re.compile(r"^\s*use\s+([A-Za-z_][\w\\]*)", re.M)],
})

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


# Common control-flow keywords that regex def-rules can mistake for a name.
_SKIP_NAMES = frozenset({
    "if", "for", "while", "switch", "return", "catch", "else", "do", "case",
    "in", "of", "new", "and", "or", "not", "with", "as", "is", "end",
})

# Conservative universal ruleset for the long-tail languages that have no
# dedicated rules. Keyword-led and line-anchored; the {0,6} modifier prefix is
# bounded (ReDoS-safe) and _cap_lines bounds line length.
_GENERIC_DEFS = [
    (re.compile(rf"^\s*{_MOD}(?:function|func|fn|def|defn|defp|sub|proc|fun|method|routine|macro|template|iterator)\s+([A-Za-z_][\w.'!?-]*)", re.M), FUNCTION),
    (re.compile(rf"^\s*{_MOD}(?:class|struct|interface|trait|enum|type|module|package|object|record|contract|protocol|mixin|namespace|union|actor)\s+([A-Za-z_][\w.'-]*)", re.M), CLASS),
    # C-family declaration: `<type> name(...) {` (covers D, Vala, Verilog, etc.).
    # The required trailing `{` keeps false positives low.
    (re.compile(r"^[A-Za-z_][\w\s\*<>,]{0,200}?\b([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{", re.M), FUNCTION),
]


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
                if not name or name in _SKIP_NAMES:
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


class GenericExtractor(Extractor):
    """Best-effort symbols for languages without dedicated rules, using a small
    universal keyword-led heuristic. Never emits import edges (too language-
    specific to guess safely); the file still becomes a searchable node."""

    key = "generic"

    def extract(self, rel_path: str, text: str, file_id: str, lang: str):
        nodes: list[Node] = []
        edges: list[Edge] = []
        seen: set[str] = set()
        text = _cap_lines(text)
        for pattern, kind in _GENERIC_DEFS:
            for m in pattern.finditer(text):
                name = m.group(1)
                if not name or name.lower() in _SKIP_NAMES:
                    continue
                nid = node_id(rel_path, name)
                if nid in seen:
                    continue
                seen.add(nid)
                nodes.append(Node(
                    id=nid, kind=kind, name=name, path=rel_path,
                    line=line_of(text, m.start()), qualname=name, lang=lang,
                ))
                edges.append(Edge(src=file_id, dst=nid, kind=DEFINES))
        return nodes, edges
