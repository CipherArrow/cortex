"""Config-file extractor for yaml/toml/json.

Emits a light set of top-level key nodes so config schemas (e.g. a single
source-of-truth settings file) show up in the map without exploding into noise.
JSON is size-capped and only its top-level object keys are surfaced.
"""

from __future__ import annotations

import json
import re
import tomllib

from ..model import CONFIG_KEY, CONTAINS, Edge, Node, node_id
from .base import Extractor

# Top-level YAML key at column 0: `key:` (not a list item, not indented).
_YAML_TOPKEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:", re.M)
# INI section headers, and `key=`/`key:` at column 0 for ini/properties/dotenv.
_INI_SECTION = re.compile(r"^\[([^\]]+)\]", re.M)
_KV_KEY = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][\w.-]*)\s*[=:]", re.M)
_MAX_KEYS = 60


class ConfigExtractor(Extractor):
    key = "config"

    def extract(self, rel_path: str, text: str, file_id: str, lang: str):
        keys: list[str] = []
        if lang == "toml":
            try:
                data = tomllib.loads(text)
                keys = list(data.keys())
            except Exception:
                keys = []
        elif lang == "json":
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    keys = list(data.keys())
            except Exception:
                keys = []
        elif lang == "yaml":
            seen: list[str] = []
            for m in _YAML_TOPKEY.finditer(text):
                k = m.group(1)
                if k not in seen:
                    seen.append(k)
            keys = seen
        elif lang in ("ini", "properties", "dotenv"):
            seen = []
            for pat in (_INI_SECTION, _KV_KEY):
                for m in pat.finditer(text):
                    k = m.group(1)
                    if k not in seen:
                        seen.append(k)
            keys = seen

        nodes: list[Node] = []
        edges: list[Edge] = []
        for k in keys[:_MAX_KEYS]:
            qual = f"key:{k}"
            nid = node_id(rel_path, qual)
            nodes.append(Node(id=nid, kind=CONFIG_KEY, name=k, path=rel_path,
                              qualname=qual, lang=lang))
            edges.append(Edge(src=file_id, dst=nid, kind=CONTAINS))
        return nodes, edges

    def summary(self, keys_count: int) -> str:
        return f"{keys_count} top-level keys" if keys_count else ""
