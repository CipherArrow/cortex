"""Security regression tests — locks in the hardening from the audit.

Run:  PYTHONPATH=<cortex-root> python3 tests/test_security.py
"""

from __future__ import annotations

import http.client
import os
import stat
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cortex import scan as S
from cortex import serve as SRV
from cortex.config import load_config
from cortex.emit_html import render_page
from cortex.store import load_graph


def check(cond, msg):
    print(("ok: " if cond else "FAIL: ") + msg)
    if not cond:
        sys.exit(1)


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, "utf-8")


def test_xss(root):
    # A malicious docstring that tries to break out of the <script> data blob.
    payload = '</script><img src=x onerror=alert(document.domain)>'
    _write(root, "evil.py", f'"""{payload}"""\ndef f():\n    return 1\n')
    S.full_scan(root)
    g = load_graph(load_config(root))
    html = render_page(g)
    check("</script><img" not in html, "no raw </script> breakout in served HTML")
    check("onerror=alert" not in html or "\\u003c" in html,
          "injected markup is escaped, not live")
    check("<img src=x" not in html, "no live <img> injected from scanned content")


def test_symlink_escape(root):
    # A symlink pointing outside the project must not be read into the graph.
    secret = Path(tempfile.mkdtemp()) / "secret.py"
    secret.write_text('SECRET_TOKEN = "do-not-leak-1234"\n', "utf-8")
    link = root / "linked.py"
    try:
        os.symlink(secret, link)
    except OSError:
        print("ok: (symlinks unavailable, skipping escape test)")
        return
    S.full_scan(root)
    graph_json = (root / ".cortex" / "graph.json").read_text("utf-8")
    check("do-not-leak" not in graph_json, "symlink target outside root is not scanned")
    check("SECRET_TOKEN" not in graph_json, "escaped symlink's symbols not indexed")


def test_permissions(root):
    """Every file SECURITY.md names as owner-only must actually be owner-only.

    The doc promises 0600 for six files; this used to check three, so the other
    three could regress without failing anything. Generate the lazily-created
    ones first so the check is never vacuously skipped.
    """
    from cortex import query as Q
    from cortex.cli import main as cli_main

    S.full_scan(root)
    d = root / ".cortex"

    cli_main(["-C", str(root), "graph", "--format", "html"])   # writes graph.html
    Q.search(load_config(root), "helper")                       # writes activity.jsonl

    dmode = stat.S_IMODE(d.stat().st_mode)
    check(dmode == 0o700, f".cortex dir is owner-only (0700), got {oct(dmode)}")

    documented = ("graph.json", "index.db", "manifest.json",
                  "MAP.md", "graph.html", "activity.jsonl")
    for f in documented:
        p = d / f
        check(p.exists(), f".cortex/{f} exists (else the 0600 check is vacuous)")
        m = stat.S_IMODE(p.stat().st_mode)
        check(m == 0o600, f".cortex/{f} is owner-only (0600), got {oct(m)}")


def test_export_leaves_the_private_dir(root):
    """`graph -o` is documented as the deliberate exception — verify it is one.

    SECURITY.md tells readers to treat an export as publishing, so the export
    must genuinely land outside .cortex and must not be silently hardened to
    0600 (which would make the documented advice wrong in the other direction).
    """
    from cortex.cli import main as cli_main

    S.full_scan(root)
    out = root / "exported_graph.html"
    cli_main(["-C", str(root), "graph", "--format", "html", "-o", str(out)])

    check(out.is_file(), "graph -o writes to the requested path")
    check(".cortex" not in out.parts, "the export lands outside the private index")

    expected = 0o666 & ~_current_umask()
    mode = stat.S_IMODE(out.stat().st_mode)
    check(mode == expected,
          f"export respects the caller's umask (got {oct(mode)}, "
          f"expected {oct(expected)}) rather than being forced to 0600")


def _current_umask() -> int:
    prev = os.umask(0)
    os.umask(prev)
    return prev


def test_special_files(root):
    """A FIFO/device named like a source file must not block the scan.

    Opening a named pipe blocks until a writer appears, so without a
    regular-file guard a single `mkfifo evil.py` hangs `cortex scan` forever.
    """
    import signal
    d = root / "specials"
    d.mkdir(exist_ok=True)
    (d / "real.py").write_text("def real_fn():\n    return 1\n", "utf-8")
    fifo = d / "trap.py"
    tag_fifo = d / "cachelike"
    try:
        os.mkfifo(fifo)
        tag_fifo.mkdir(exist_ok=True)
        os.mkfifo(tag_fifo / "CACHEDIR.TAG")   # the other open() path
    except (AttributeError, OSError, NotImplementedError):
        print("ok: (mkfifo unavailable, skipping special-file test)")
        return

    def _hung(signum, frame):
        raise TimeoutError("scan hung on a special file")

    prev = signal.signal(signal.SIGALRM, _hung)
    signal.alarm(20)
    try:
        S.full_scan(root)
        check(True, "scan completes with FIFOs present (no hang)")
    except TimeoutError:
        check(False, "scan completes with FIFOs present (no hang)")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev)

    graph_json = (root / ".cortex" / "graph.json").read_text("utf-8")
    check("trap.py" not in graph_json, "FIFO is not indexed as a source file")
    check("real_fn" in graph_json, "regular files beside a FIFO still index")


def test_serve_auth(root):
    S.full_scan(root)
    cfg = load_config(root)
    httpd, token, port = SRV.make_server(cfg, port=0, limit=50)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        def get(path, headers=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", path, headers=headers or {})
            r = c.getresponse()
            body = r.read()
            c.close()
            return r.status, r.getheader("Set-Cookie"), body

        st, _, _ = get("/")
        check(st == 401, "GET / without token -> 401")
        st, _, _ = get("/activity")
        check(st == 401, "GET /activity without token -> 401")
        st, _, _ = get("/?t=wrong-token-value")
        check(st == 401, "GET / with wrong token -> 401")
        st, cookie, _ = get(f"/?t={token}")
        check(st == 302 and cookie and "SameSite=Strict" in cookie and "HttpOnly" in cookie,
              "GET /?t=<token> -> 302 with HttpOnly SameSite=Strict cookie")
        st, _, _ = get("/activity", {"X-Cortex-Token": token})
        check(st == 200, "GET /activity with token header -> 200")
        st, _, _ = get("/", {"Host": "evil.example.com", "X-Cortex-Token": token})
        check(st == 403, "spoofed Host header -> 403 even with valid token")
        # method restriction
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("POST", "/", headers={"X-Cortex-Token": token})
        check(c.getresponse().status == 405, "POST -> 405 (GET only)")
        c.close()
    finally:
        httpd.shutdown()
        httpd.server_close()


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root, "pkg/mod.py", '"""m."""\ndef helper():\n    return 1\n')
        test_xss(root)
        test_symlink_escape(root)
        test_permissions(root)
        test_export_leaves_the_private_dir(root)
        test_special_files(root)
        test_serve_auth(root)
    print("\nALL SECURITY CHECKS PASSED")


if __name__ == "__main__":
    main()
