"""Command-line interface: scan, sync, query, context, hubs, status, graph, ...

Designed to be trivially driven by any agent: every read command prints compact,
paste-ready text; add --json to any of them for machine consumption.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import CLI_NAME, DATA_DIR, TOOL_NAME, __version__
from .config import DEFAULT_CONFIG_TOML, load_config
from . import query as Q
from . import scan as S


# --- project root discovery --------------------------------------------------
def find_root(start: str) -> Path:
    p = Path(start).resolve()
    for cand in [p, *p.parents]:
        if (cand / DATA_DIR).is_dir():
            return cand
    return p  # not initialised yet; caller may still scan here


# --- output helpers ----------------------------------------------------------
def _fmt_node(n: dict) -> str:
    loc = f"{n['path']}:{n['line']}" if n.get("path") else f"({n['kind']})"
    name = n.get("qualname") or n.get("name")
    rank = n.get("rank", 0)
    summ = f"  — {n['summary']}" if n.get("summary") else ""
    return f"  {loc:<40} {n['kind']:<9} {name}{summ}  [r={rank}]"


def _emit(rows, as_json: bool, empty_msg: str) -> int:
    if as_json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    if rows is None:
        print(f"No {TOOL_NAME} index found. Run `{CLI_NAME} scan` first.", file=sys.stderr)
        return 2
    if not rows:
        print(empty_msg)
        return 0
    for r in rows:
        print(_fmt_node(r))
    return 0


# --- commands ----------------------------------------------------------------
def cmd_init(args) -> int:
    root = Path(args.dir).resolve()
    cfg = load_config(root)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg.data_dir / "config.toml"
    if not cfg_path.exists():
        cfg_path.write_text(DEFAULT_CONFIG_TOML, "utf-8")
    print(f"Initialising {TOOL_NAME} in {root} …")
    return cmd_scan(args)


def cmd_scan(args) -> int:
    root = Path(args.dir).resolve()
    t0 = time.time()
    meta = S.full_scan(root)
    dt = time.time() - t0
    st = meta["stats"]
    print(f"Scanned {meta.get('files', '?')} files → "
          f"{st['nodes']} nodes, {st['edges']} edges in {dt:.2f}s")
    print(f"  map:   {root / DATA_DIR / 'MAP.md'}")
    print(f"  index: {root / DATA_DIR / 'index.db'}")
    return 0


def cmd_sync(args) -> int:
    root = find_root(args.dir)
    t0 = time.time()
    meta = S.sync(root, changed=args.changed)
    dt = time.time() - t0
    kind = meta.get("scan", "?")
    if kind == "noop":
        print("Up to date; nothing changed.")
        return 0
    st = meta["stats"]
    ch = meta.get("changed", {})
    detail = ""
    if ch:
        detail = f" (touched {len(ch.get('touched', []))}, removed {len(ch.get('removed', []))})"
    print(f"Sync [{kind}]{detail} → {st['nodes']} nodes, {st['edges']} edges in {dt:.2f}s")
    return 0


def cmd_query(args) -> int:
    cfg = load_config(find_root(args.dir))
    rows = Q.search(cfg, args.term, kind=args.kind, limit=args.limit)
    return _emit(rows, args.json, f"No matches for '{args.term}'.")


def cmd_context(args) -> int:
    cfg = load_config(find_root(args.dir))
    res = Q.context(cfg, args.ref)
    if res is None:
        print(f"No {TOOL_NAME} index found. Run `{CLI_NAME} scan` first.", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    if "error" in res:
        print(res["error"])
        return 1
    n = res["node"]
    print(f"# {n.get('qualname') or n['name']}  ({n['kind']})")
    if n.get("path"):
        print(f"  defined at {n['path']}:{n['line']}   [rank {n.get('rank', 0)}]")
    if n.get("summary"):
        print(f"  {n['summary']}")
    for label, key in (("called by", "callers"), ("calls", "callees"),
                       ("imported/referenced by", "importers"),
                       ("siblings in file", "siblings")):
        rows = res.get(key) or []
        if rows:
            print(f"\n  {label}:")
            for r in rows:
                loc = f"{r['path']}:{r['line']}" if r.get("path") else f"({r['kind']})"
                print(f"    - {r.get('qualname') or r['name']}  {loc}")
    return 0


def cmd_neighbors(args) -> int:
    cfg = load_config(find_root(args.dir))
    res = Q.neighbors(cfg, args.ref)
    if res is None:
        print(f"No {TOOL_NAME} index found. Run `{CLI_NAME} scan` first.", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    if "error" in res:
        print(res["error"])
        return 1
    print(f"# {res['node'].get('qualname') or res['node']['name']}")
    print("\n  outgoing:")
    for r in res["outgoing"]:
        print(f"    -{r['edge']:>11}-> {r.get('qualname') or r['name']}  ({r['kind']})")
    print("\n  incoming:")
    for r in res["incoming"]:
        print(f"    <-{r['edge']:>11}- {r.get('qualname') or r['name']}  ({r['kind']})")
    return 0


def cmd_importers(args) -> int:
    cfg = load_config(find_root(args.dir))
    res = Q.neighbors(cfg, args.ref)
    if res is None:
        print(f"No {TOOL_NAME} index found. Run `{CLI_NAME} scan` first.", file=sys.stderr)
        return 2
    if "error" in res:
        print(res["error"]); return 1
    deps = [r for r in res["incoming"]
            if r["edge"] in ("imports", "references", "links_to", "calls")]
    return _emit(deps, args.json, "Nothing depends on this yet.")


def cmd_hubs(args) -> int:
    cfg = load_config(find_root(args.dir))
    rows = Q.hubs(cfg, limit=args.limit, kind=args.kind)
    return _emit(rows, args.json, "No ranked nodes.")


def cmd_status(args) -> int:
    root = find_root(args.dir)
    cfg = load_config(root)
    stats = Q.get_stats(cfg)
    if stats is None:
        print(f"Not initialised. Run `{CLI_NAME} scan` in {root}.")
        return 2
    gen = stats.pop("generated_at", 0)
    ago = int(time.time()) - gen if gen else 0
    print(f"{TOOL_NAME} v{__version__} — {root}")
    print(f"  generated: {time.strftime('%Y-%m-%d %H:%M', time.localtime(gen))} "
          f"({ago // 60} min ago)")
    print(f"  nodes: {stats.get('nodes')}   edges: {stats.get('edges')}")
    print(f"  node kinds: {stats.get('node_kinds')}")
    # staleness check
    from .walker import diff_manifest, load_manifest, scan_manifest
    diff = diff_manifest(load_manifest(cfg), scan_manifest(cfg))
    if diff.is_empty:
        print("  status: up to date ✓")
    else:
        print(f"  status: STALE — +{len(diff.added)} ~{len(diff.changed)} "
              f"-{len(diff.removed)}  (run `{CLI_NAME} sync`)")
    return 0


def cmd_graph(args) -> int:
    cfg = load_config(find_root(args.dir))
    from .store import load_graph
    g = load_graph(cfg)
    if g is None:
        print(f"No index. Run `{CLI_NAME} scan` first.", file=sys.stderr)
        return 2
    from . import emit_mermaid as M
    if args.format == "mermaid":
        print(M.to_mermaid(g, limit=args.limit))
    elif args.format == "dot":
        print(M.to_dot(g, limit=args.limit))
    elif args.format == "html":
        from . import emit_html as HT
        out = cfg.data_dir / "graph.html"
        out.write_text(HT.render_page(g, limit=args.limit,
                                      title=f"Cortex — {cfg.root.name}"), "utf-8")
        print(f"Interactive graph written to {out}")
        print("Open it in a browser (double-click or `xdg-open`).")
    else:  # json
        print(cfg.data_dir / "graph.json")
    return 0


def cmd_serve(args) -> int:
    cfg = load_config(find_root(args.dir))
    from .serve import serve
    serve(cfg, port=args.port, limit=args.limit)
    return 0


def cmd_install_hook(args) -> int:
    from .hookgen import render_hook_instructions
    print(render_hook_instructions())
    return 0


def cmd_doctor(args) -> int:
    import sqlite3
    print(f"{TOOL_NAME} v{__version__} doctor")
    print(f"  python: {sys.version.split()[0]}")
    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        print("  sqlite fts5: available (fast search)")
    except Exception:
        print("  sqlite fts5: MISSING (falls back to LIKE search)")
    root = find_root(args.dir)
    cfg = load_config(root)
    print(f"  project root: {root}")
    print(f"  initialised: {'yes' if cfg.data_dir.is_dir() else 'no'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=CLI_NAME,
        description=f"{TOOL_NAME} — a self-updating project knowledge graph for AI agents.")
    p.add_argument("-C", "--dir", default=".", help="project directory (default: cwd)")
    p.add_argument("-V", "--version", action="version", version=f"{TOOL_NAME} {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="create .cortex/ config and run the first scan")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("scan", help="full (re)scan of the project")
    sp.add_argument("--force", action="store_true", help="(accepted; scan is always full)")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("sync", help="incremental update of changed files")
    sp.add_argument("--changed", nargs="*", help="explicit changed file paths")
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("query", help="find files/symbols/headings by name or summary")
    sp.add_argument("term")
    sp.add_argument("--kind", help="filter: file/module/class/function/method/heading/concept")
    sp.add_argument("-n", "--limit", type=int, default=20)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_query)

    sp = sub.add_parser("context", help="definition + callers + callees + siblings")
    sp.add_argument("ref")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_context)

    sp = sub.add_parser("neighbors", help="all incoming/outgoing edges of a node")
    sp.add_argument("ref")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_neighbors)

    sp = sub.add_parser("importers", help="what depends on a file/symbol")
    sp.add_argument("ref")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_importers)

    sp = sub.add_parser("hubs", help="most central (most depended-upon) nodes")
    sp.add_argument("-n", "--limit", type=int, default=20)
    sp.add_argument("--kind")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_hubs)

    sp = sub.add_parser("status", help="show index stats and staleness")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("graph", help="export the graph (mermaid/dot/html/json)")
    sp.add_argument("--format", choices=["mermaid", "dot", "html", "json"], default="mermaid")
    sp.add_argument("-n", "--limit", type=int, default=60)
    sp.set_defaults(func=cmd_graph)

    sp = sub.add_parser("serve", help="live graph on localhost — glows as agents access nodes")
    sp.add_argument("--port", type=int, default=8377)
    sp.add_argument("-n", "--limit", type=int, default=250)
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("install-hook", help="print the Claude Code auto-sync hook block")
    sp.set_defaults(func=cmd_install_hook)

    sp = sub.add_parser("doctor", help="environment / setup check")
    sp.set_defaults(func=cmd_doctor)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
