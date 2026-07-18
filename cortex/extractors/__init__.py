"""Extractor registry: choose an extractor by its key (from config.EXT_LANG)."""

from __future__ import annotations

from .base import Extractor
from .config_files import ConfigExtractor
from .markdown import MarkdownExtractor
from .python_ast import PythonExtractor
from .regex_generic import RegexExtractor

_REGISTRY = {
    "python": PythonExtractor(),
    "regex": RegexExtractor(),
    "markdown": MarkdownExtractor(),
    "config": ConfigExtractor(),
}


def get_extractor(key: str) -> Extractor | None:
    return _REGISTRY.get(key)
