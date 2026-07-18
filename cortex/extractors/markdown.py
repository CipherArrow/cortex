"""Markdown / prose extractor.

Turns a document into headings, [[wikilinks]], [text](links) and #tags — the
building blocks of an Obsidian-style knowledge graph. This is what lets Cortex
map *prose* projects (worldbuilding, notes, docs) as well as code.
"""

from __future__ import annotations

import re

from ..model import (CONCEPT, CONTAINS, HEADING, LINKS_TO, REFERENCES, TAGGED,
                     Edge, Node, node_id)
from .base import Extractor, line_of

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.M)
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
_MDLINK = re.compile(r"(?<!\!)\[[^\]]+\]\(([^)]+)\)")
_TAG = re.compile(r"(?:^|\s)#([A-Za-z][\w/-]{1,40})")
_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`[^`]*`")


def _strip_code(text: str) -> str:
    """Blank out fenced and inline code so tags/links inside code don't count.
    Newlines are preserved so line numbers stay accurate."""
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    text = _FENCE.sub(blank, text)
    text = _INLINE_CODE.sub(blank, text)
    return text


class MarkdownExtractor(Extractor):
    key = "markdown"

    def extract(self, rel_path: str, text: str, file_id: str, lang: str):
        nodes: list[Node] = []
        edges: list[Edge] = []
        clean = _strip_code(text)

        for m in _HEADING.finditer(clean):
            title = m.group(2).strip()
            level = len(m.group(1))
            qual = f"h{level}:{title}"
            nid = node_id(rel_path, qual)
            nodes.append(Node(
                id=nid, kind=HEADING, name=title, path=rel_path,
                line=line_of(clean, m.start()), qualname=qual, lang="markdown",
                summary=f"H{level}",
            ))
            edges.append(Edge(src=file_id, dst=nid, kind=CONTAINS))

        for m in _WIKILINK.finditer(clean):
            edges.append(Edge(src=file_id, dst="", kind=REFERENCES, raw=m.group(1).strip()))

        for m in _MDLINK.finditer(clean):
            target = m.group(1).strip()
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            edges.append(Edge(src=file_id, dst="", kind=LINKS_TO, raw=target.split("#")[0]))

        tags: set[str] = set()
        for m in _TAG.finditer(clean):
            tags.add(m.group(1))
        for tag in tags:
            cid = node_id("", f"tag:{tag}")
            nodes.append(Node(id=cid, kind=CONCEPT, name=f"#{tag}", qualname=f"tag:{tag}"))
            edges.append(Edge(src=file_id, dst=cid, kind=TAGGED))

        return nodes, edges

    def title(self, text: str) -> str:
        """First H1 (or first heading) as a document summary."""
        m = _HEADING.search(_strip_code(text))
        return m.group(2).strip() if m else ""
