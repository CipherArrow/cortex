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

        test_tail_index_equivalence()
        test_tail_index_is_used(root)
        test_model_dicts_cover_all_fields()
        test_glob_matcher_equivalence(root)
        test_hook_syncs_and_fails_safe(root)

        print("\nALL SMOKE CHECKS PASSED")


def test_hook_syncs_and_fails_safe(root: Path):
    """The auto-sync hook must update the map, and must never fail an edit.

    The body lives in the package rather than in hooks/ specifically so that an
    installed copy has it — a wheel ships `cortex/`, not the repo's top-level
    directories, so a path-based hook pointed into site-packages/hooks/ would
    reference a file that does not exist.
    """
    import io
    import json as _json

    from cortex import hook as H
    from cortex.hookgen import hook_block, hook_command

    cfg = load_config(root)

    # A real edit inside a mapped project reaches the index.
    _write(root, "pkg/hooked.py", "def hooked_symbol():\n    return 1\n")
    payload = _json.dumps({"tool_input": {"file_path": str(root / "pkg/hooked.py")}})
    rc = H.run(io.StringIO(payload))
    check(rc == 0, "hook exits 0 on a normal edit")
    rows = Q.search(cfg, "hooked_symbol")
    check(any(r["name"] == "hooked_symbol" for r in rows),
          "hook synced the edited file into the index")

    # Everything it cannot handle must still exit 0 — a map refresh must never
    # fail the user's write.
    for label, data in (
        ("malformed json", "not json at all"),
        ("empty stdin", ""),
        ("no file_path", '{"tool_input": {}}'),
        ("file outside any project", '{"tool_input": {"file_path": "/nonexistent/x.py"}}'),
    ):
        check(H.run(io.StringIO(data)) == 0, f"hook exits 0 on {label}")

    # The generated command must name something that exists, or install-hook is
    # handing users a broken line.
    cmd = hook_command()
    target = cmd.split()[0]
    check(Path(target).exists(), f"install-hook's command starts with a real path ({target})")
    entry = hook_block()["PostToolUse"][0]["hooks"][0]
    check(entry["command"] == cmd and entry["timeout"] > 0,
          "hook block carries the resolved command and a timeout")


def test_glob_matcher_equivalence(root: Path):
    """The compiled ignore-glob regex must decide exactly what fnmatch decided.

    Getting this wrong doesn't crash — it silently changes which files are
    indexed, in either direction. So compare against fnmatch itself rather than
    against a fixture of expected answers.
    """
    import random
    import string
    from fnmatch import fnmatch

    from cortex.walker import _glob_matcher

    globs = load_config(root).ignore_globs
    match = _glob_matcher(globs)

    def agrees(name):
        return match(name) == any(fnmatch(name, g) for g in globs)

    named = ["a.py", "x.pyc", ".env", "test.min.js", "foo.lock", "a.b.c.py", "",
             ".hidden", "UPPER.PY", "file.tar.gz", "x.map", "a.egg-info",
             "package-lock.json", ".DS_Store", "core.py", "a~"]
    check(all(agrees(n) for n in named),
          f"compiled ignore-globs agree with fnmatch ({len(named)} known names)")

    random.seed(3)
    alphabet = string.ascii_letters + "._-*?[]"
    fuzz = ["".join(random.choice(alphabet) for _ in range(random.randint(1, 14)))
            for _ in range(2000)]
    bad = [n for n in fuzz if not agrees(n)]
    check(not bad, f"compiled ignore-globs agree with fnmatch on 2000 fuzzed names"
                   f"{' — first mismatch: ' + repr(bad[0]) if bad else ''}")

    check(_glob_matcher([])("anything.py") is False,
          "empty glob list ignores nothing")


def test_model_dicts_cover_all_fields():
    """to_dict() is hand-written for speed, so it can drift from the dataclass.

    A field added to Node/Edge but missed in to_dict would silently stop being
    persisted — the graph would still load, just quietly lose data. Compare
    against the dataclass definition instead of a hardcoded list, and round-trip
    to prove the values survive.
    """
    from cortex.model import Edge, Node

    for cls, sample in (
        (Node, Node(id="i", kind="function", name="n", path="p.py", line=3,
                    qualname="q", lang="python", summary="s", loc=9, rank=0.5)),
        (Edge, Edge(src="a", dst="b", kind="imports", raw="x.y")),
    ):
        declared = set(cls.__dataclass_fields__)
        emitted = set(sample.to_dict())
        missing = declared - emitted
        check(not missing,
              f"{cls.__name__}.to_dict emits every field "
              f"(missing: {sorted(missing) or 'none'})")
        check(not (emitted - declared),
              f"{cls.__name__}.to_dict emits no unknown field")
        check(cls.from_dict(sample.to_dict()) == sample,
              f"{cls.__name__} survives a to_dict/from_dict round trip")


def test_tail_index_is_used(root: Path):
    """resolve() must hand the prebuilt index down, not fall back to scanning.

    Equivalence alone would still pass if the call site stopped passing the
    index — and the cost of that regression is quadratic, so it is worth
    asserting the wiring directly.
    """
    import cortex.graph as G

    got_index = []
    original = G._match_py

    def spy(rel, by_path, by_tail=None):
        got_index.append(by_tail is not None)
        return original(rel, by_path, by_tail)

    G._match_py = spy
    try:
        S.full_scan(root)
    finally:
        G._match_py = original

    check(bool(got_index), "python import resolution ran during the scan")
    check(all(got_index),
          f"every _match_py call got the prebuilt index ({len(got_index)} calls)")


def test_tail_index_equivalence():
    """The prebuilt tail index must answer exactly like the linear scan.

    _match_py's tail fallback is served from an index built once per resolve()
    instead of scanning every path per import edge. The two must stay in
    agreement, or the speedup would silently change which imports resolve.
    """
    import posixpath

    from cortex.graph import _match_py

    by_path = {
        "pkg/util.py": "id-util",
        "pkg/sub/util.py": "id-sub-util",       # duplicate tail: first must win
        "pkg/core.py": "id-core",
        "top.py": "id-top",                      # no directory component
        "web/lib.js": "id-lib",                  # non-Python must be ignored
        "pkg/__init__.py": "id-init",
    }
    # Built exactly as Graph.resolve() builds it.
    by_tail = {}
    for path, nid in by_path.items():
        if path.endswith(".py"):
            by_tail.setdefault(posixpath.basename(path), nid)

    cases = ["util", "pkg/util", "deep/nested/util", "core", "top",
             "lib", "missing", "sub/util", "__init__", ""]
    mismatches = [c for c in cases
                  if _match_py(c, by_path, by_tail) != _match_py(c, by_path, None)]
    check(not mismatches, f"tail index matches the linear scan on all inputs "
                          f"({len(cases)} cases)")
    # Non-vacuous: the fallback must actually be exercised, not all-empty.
    check(_match_py("deep/nested/util", by_path, by_tail) == "id-util",
          "tail fallback still resolves a nested import to the first match")


if __name__ == "__main__":
    main()
