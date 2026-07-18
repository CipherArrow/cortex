"""End-to-end smoke test: build a tiny mixed project, scan, and query it.

Run:  PYTHONPATH=<cortex-root> python3 tests/test_smoke.py
Exits non-zero on the first failed assertion.
"""

from __future__ import annotations

import sys
import tempfile
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cortex import scan as S
from cortex import query as Q
from cortex.config import load_config


def _write(root: Path, rel: str, text: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, "utf-8")


def build_fixture(root: Path):
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/core.py",
           '"""Core module."""\n'
           "from .util import helper\n\n"
           "class Engine:\n"
           "    \"\"\"The engine.\"\"\"\n"
           "    def run(self):\n"
           "        return helper()\n")
    _write(root, "pkg/util.py",
           '"""Utilities."""\n\n'
           "def helper():\n"
           "    \"\"\"Do a thing.\"\"\"\n"
           "    return 42\n")
    _write(root, "web/app.js",
           "import { thing } from './lib';\n"
           "export function main() { return thing(); }\n")
    _write(root, "web/lib.js",
           "export function thing() { return 1; }\n")
    _write(root, "docs/Overview.md",
           "# Overview\n\nSee [[core]] and the [util](../pkg/util.py) module. #design\n")
    # A self-tagged cache directory (Cache Directory Tagging Specification).
    # Its contents must never be indexed, however source-like they look.
    _write(root, "vendor_cache/CACHEDIR.TAG",
           "Signature: 8a477f597d28d172789f06886806bc55\n")
    _write(root, "vendor_cache/deep/vendored.py",
           "def vendored_symbol():\n    return 1\n")
    # A legacy escape in a non-raw string makes CPython warn at compile time.
    # The file must still index, and the warning must not reach our output.
    _write(root, "pkg/legacy_escape.py",
           "import re\n\n\n"
           "def match_key(s):\n"
           '    return re.match("^K\\d+$", s)\n')


def check(cond, msg):
    if not cond:
        print(f"FAIL: {msg}")
        sys.exit(1)
    print(f"ok: {msg}")


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build_fixture(root)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            meta = S.full_scan(root)
        cfg = load_config(root)

        check(meta["stats"]["nodes"] > 10, "produced nodes")
        check(meta["stats"]["edges"] > 5, "produced edges")

        rows = Q.search(cfg, "helper")
        check(any(r["name"] == "helper" for r in rows), "query finds function 'helper'")

        rows = Q.search(cfg, "Engine", kind="class")
        check(any(r["name"] == "Engine" for r in rows), "query finds class 'Engine'")

        ctx = Q.context(cfg, "pkg/util.py")
        importers = {r["path"] for r in ctx["importers"]}
        check("pkg/core.py" in importers, "python import edge core.py -> util.py")

        # JS relative import resolves internally
        nb = Q.neighbors(cfg, "web/app.js")
        outs = {r["name"] for r in nb["outgoing"]}
        check("lib.js" in outs, "js import edge app.js -> lib.js")

        # markdown wikilink [[core]] resolves to core.py
        nb = Q.neighbors(cfg, "docs/Overview.md")
        ref_targets = {r["name"] for r in nb["outgoing"] if r["kind"] in ("module", "file")}
        check("core.py" in ref_targets, "wikilink [[core]] -> core.py")

        # heading + tag concept exist
        rows = Q.search(cfg, "Overview")
        check(any(r["kind"] == "heading" for r in rows), "markdown heading indexed")

        # a self-tagged cache directory is pruned, contents and all
        rows = Q.search(cfg, "vendored_symbol")
        check(not any(r["name"] == "vendored_symbol" for r in rows),
              "CACHEDIR.TAG directory is not indexed")

        # the scanned project's compile warnings stay out of our output
        check(not any(issubclass(w.category, SyntaxWarning) for w in caught),
              "scanned file's SyntaxWarning is not leaked")
        rows = Q.search(cfg, "match_key")
        check(any(r["name"] == "match_key" for r in rows),
              "file with a legacy escape still indexes")

        # incremental sync picks up a new file
        _write(root, "pkg/extra.py", "def brand_new():\n    return 1\n")
        S.sync(root, changed=[str(root / "pkg/extra.py")])
        rows = Q.search(cfg, "brand_new")
        check(any(r["name"] == "brand_new" for r in rows), "sync indexes a new file")

        print("\nALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
