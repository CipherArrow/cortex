"""Language-coverage regression test for the broadened extractor set.

Builds a fixture with many languages + special filenames, scans it, and asserts
that symbols, imports, generic-fallback symbols, and file nodes appear as
expected.

Run:  PYTHONPATH=<cortex-root> python3 tests/test_languages.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cortex import query as Q
from cortex import scan as S
from cortex.config import load_config


def check(cond, msg):
    print(("ok: " if cond else "FAIL: ") + msg)
    if not cond:
        sys.exit(1)


def _w(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, "utf-8")


FIXTURES = {
    "app.swift": "import Foundation\npublic func greet(n: String) {}\nstruct Point {}\n",
    "Main.kt": "package a\nimport x.y.Z\nfun compute(): Int = 1\nclass Widget {}\n",
    "svc.scala": "import a.b.C\ndef run(): Unit = ()\nobject App {}\n",
    "ui.dart": "import 'x.dart';\nclass Home {}\nvoid main() {}\n",
    "util.lua": "local function add(a,b) return a+b end\n",
    "mod.ex": "defmodule My.Mod do\n  def hello, do: :world\nend\n",
    "lib.hs": "module M where\nimport Data.List\nadd :: Int -> Int\nadd x = x\n",
    "core.clj": "(ns app.core)\n(defn handler [req] req)\n",
    "Token.sol": "import './X.sol';\ncontract Token {\n  function mint() public {}\n}\n",
    "solve.jl": "using LinearAlgebra\nfunction solve(x)\nend\n",
    "thing.d": "class Foo {}\nvoid bar() {}\n",         # generic fallback
    "config.ini": "[server]\nport=8080\n",             # config keys
    "Dockerfile": "FROM alpine\nRUN echo hi\n",         # special filename, file node
    "Makefile": "build:\n\tgcc x.c\n",                  # special filename, generic
    "Gemfile": "source 'https://rubygems.org'\ndef helper\nend\n",  # special -> ruby
}


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for rel, text in FIXTURES.items():
            _w(root, rel, text)
        S.full_scan(root)
        cfg = load_config(root)

        def has(term, kind=None, name=None):
            rows = Q.search(cfg, term, kind=kind, limit=50) or []
            if name:
                return any(r["name"] == name for r in rows)
            return bool(rows)

        # Tier-2 symbols
        check(has("greet", name="greet"), "swift function extracted")
        check(has("Widget", kind="class", name="Widget"), "kotlin class extracted")
        check(has("run", name="run"), "scala def extracted")
        check(has("Home", name="Home"), "dart class extracted")
        check(has("add", name="add"), "lua/haskell function extracted")
        check(has("hello", name="hello"), "elixir def extracted")
        check(has("handler", name="handler"), "clojure defn extracted")
        check(has("mint", name="mint"), "solidity function extracted")
        check(has("solve", name="solve"), "julia function extracted")

        # import edge resolves (kotlin app -> its import target or external)
        nb = Q.neighbors(cfg, "Main.kt")
        check(any(r["edge"] == "imports" for r in nb["outgoing"]),
              "kotlin import edge present")

        # generic fallback
        check(has("Foo", kind="class", name="Foo"), "generic-fallback class (.d)")
        check(has("bar", name="bar"), "generic-fallback function (.d)")

        # config keys
        check(has("port", kind="config_key", name="port"), "ini config key extracted")

        # special filenames become nodes
        check(has("Dockerfile", name="Dockerfile"), "Dockerfile is a node")
        check(has("Makefile", name="Makefile"), "Makefile is a node")
        check(has("Gemfile", name="Gemfile"), "Gemfile is a node")
        check(has("helper", name="helper"), "Gemfile parsed as ruby (def helper)")

        stats = Q.get_stats(cfg)
        check(stats["nodes"] > 25, f"produced a populated graph ({stats['nodes']} nodes)")

    print("\nALL LANGUAGE CHECKS PASSED")


if __name__ == "__main__":
    main()
