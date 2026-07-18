"""`cortex serve` — live graph view on localhost (stdlib http.server only).

Serves the static-atlas graph page plus a `/activity` JSON endpoint the page
polls once a second. When any agent runs a Cortex lookup (query/context/…) or a
sync, the touched nodes and the paths between them glow on the map for a few
seconds. Localhost-only by design; read-only endpoints.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import TOOL_NAME
from .activity import read_since
from .config import Config
from .emit_html import render_page
from .store import load_graph

DEFAULT_PORT = 8377


def _build_page(cfg: Config, limit: int) -> bytes:
    graph = load_graph(cfg)
    if graph is None:
        return (f"<h1>{TOOL_NAME}: no index found — run a scan first.</h1>"
                .encode("utf-8"))
    return render_page(graph, limit=limit,
                       title=f"{TOOL_NAME} — {cfg.root.name} (live)").encode("utf-8")


def serve(cfg: Config, port: int = DEFAULT_PORT, limit: int = 250) -> None:
    page = _build_page(cfg, limit)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep the terminal quiet
            pass

        def _send(self, code: int, ctype: str, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                # Re-render on each page load so a fresh scan shows up on F5.
                self._send(200, "text/html; charset=utf-8", _build_page(cfg, limit))
            elif url.path == "/activity":
                q = parse_qs(url.query)
                since = int(q.get("since", ["0"])[0] or 0)
                events = read_since(cfg, since)
                self._send(200, "application/json",
                           json.dumps(events, separators=(",", ":")).encode())
            else:
                self._send(404, "text/plain", b"not found")

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"{TOOL_NAME} live graph: http://127.0.0.1:{port}/")
    print("Nodes glow as agents access them (query/context/sync). Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()
