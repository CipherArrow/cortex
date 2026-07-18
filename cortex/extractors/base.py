"""Extractor protocol shared by all language extractors.

An extractor receives one file's text plus the id of its already-created FILE
node, and returns (nodes, edges) for the symbols/links found *inside* that file.
The FILE node itself is created by the caller (scan.py), so extractors only add
children and cross-references.
"""

from __future__ import annotations

from ..model import Edge, Node


class Extractor:
    key = "base"

    def extract(self, rel_path: str, text: str, file_id: str, lang: str):
        """Return (list[Node], list[Edge]) for symbols/links in this file."""
        return [], []


def line_of(text: str, index: int) -> int:
    """1-based line number of a character offset."""
    return text.count("\n", 0, index) + 1
