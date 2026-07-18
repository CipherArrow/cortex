"""`cortex serve` — live graph view on localhost, authenticated.

Threat model this addresses (see SECURITY.md):
  * Only binds loopback (127.0.0.1) — never reachable from the LAN.
  * Every request needs an unguessable per-run token, delivered once via the
    printed URL and then held in a SameSite=Strict, HttpOnly cookie. A malicious
    web page cannot read the token (same-origin policy) nor have the cookie sent
    on its behalf (SameSite=Strict) — this defeats DNS-rebinding/CSRF sniffing.
  * Host header is allow-listed to loopback names (belt-and-suspenders vs rebinding).
  * No CORS headers, so cross-origin pages cannot read responses even if reached.
  * GET only; no directory listing; neutral Server banner; per-connection timeout.
The token lives only in memory + the printed URL — nothing sensitive on disk.
"""

from __future__ import annotations

import hmac
import json
import secrets
import sys
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import TOOL_NAME
from .activity import read_since
from .config import Config
from .emit_html import render_page
from .store import load_graph

DEFAULT_PORT = 8377
_COOKIE = "cortex_token"


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # A dropped client connection is normal; don't dump a traceback for it.
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def _build_page(cfg: Config, limit: int) -> bytes:
    graph = load_graph(cfg)
    if graph is None:
        return (f"<h1>{TOOL_NAME}: no index found — run a scan first.</h1>"
                .encode("utf-8"))
    return render_page(graph, limit=limit,
                       title=f"{TOOL_NAME} — {cfg.root.name} (live)").encode("utf-8")


def make_server(cfg: Config, port: int = DEFAULT_PORT, limit: int = 250):
    """Build (httpd, token, actual_port) without blocking — used by serve() and tests."""
    token = secrets.token_urlsafe(24)
    # ok_hosts is computed after bind so port 0 (ephemeral, for tests) resolves.
    ok_hosts: set[str] = set()

    class Handler(BaseHTTPRequestHandler):
        server_version = "Cortex"      # neutral banner, no stdlib version leak
        sys_version = ""
        timeout = 15                   # per-connection, mitigates slow-loris
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):     # keep the terminal quiet
            pass

        # -- helpers ------------------------------------------------------
        def _host_ok(self) -> bool:
            return (self.headers.get("Host") or "") in ok_hosts

        def _presented_token(self, qs: dict) -> str:
            hdr = self.headers.get("X-Cortex-Token")
            if hdr:
                return hdr
            raw = self.headers.get("Cookie")
            if raw:
                try:
                    c = SimpleCookie(raw)
                    if _COOKIE in c:
                        return c[_COOKIE].value
                except Exception:
                    pass
            return (qs.get("t", [""])[0])

        def _authed(self, qs: dict) -> bool:
            got = self._presented_token(qs)
            return bool(got) and hmac.compare_digest(got, token)

        def _headers(self, code, ctype, length, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            for k, v in (extra or []):
                self.send_header(k, v)
            self.end_headers()

        def _send(self, code, ctype, body: bytes, extra=None):
            self._headers(code, ctype, len(body), extra)
            self.wfile.write(body)

        def _deny(self, code=401):
            msg = (f"{TOOL_NAME}: unauthorized. Open the exact URL printed by "
                   f"`{TOOL_NAME.lower()} serve` (it carries a one-time token).\n")
            self._send(code, "text/plain; charset=utf-8", msg.encode())

        # -- routing ------------------------------------------------------
        def do_GET(self):
            if not self._host_ok():
                self._send(403, "text/plain", b"forbidden host")
                return
            url = urlparse(self.path)
            qs = parse_qs(url.query)

            if url.path in ("/", "/index.html"):
                # First visit carries ?t=<token>: set the cookie, then redirect
                # to a clean URL so the token doesn't linger in history.
                if qs.get("t") and hmac.compare_digest(qs["t"][0], token):
                    cookie = (f"{_COOKIE}={token}; Path=/; Max-Age=86400; "
                              f"HttpOnly; SameSite=Strict")
                    self._send(302, "text/plain", b"", extra=[("Location", "/"),
                                                              ("Set-Cookie", cookie)])
                    return
                if not self._authed(qs):
                    self._deny()
                    return
                self._send(200, "text/html; charset=utf-8", _build_page(cfg, limit),
                           extra=[("Content-Security-Policy", _CSP_HEADER)])
                return

            if url.path == "/activity":
                if not self._authed(qs):
                    self._deny()
                    return
                since = int((qs.get("since", ["0"])[0]) or 0)
                body = json.dumps(read_since(cfg, since), separators=(",", ":")).encode()
                self._send(200, "application/json", body)
                return

            self._send(404, "text/plain", b"not found")

        def _reject(self):     # any non-GET method
            if self._host_ok():
                self._send(405, "text/plain", b"method not allowed")
            else:
                self._send(403, "text/plain", b"forbidden host")

        do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = _reject

    httpd = _QuietServer(("127.0.0.1", port), Handler)
    bound = httpd.server_address[1]
    ok_hosts.update({f"127.0.0.1:{bound}", f"localhost:{bound}", "127.0.0.1", "localhost"})
    return httpd, token, bound


def serve(cfg: Config, port: int = DEFAULT_PORT, limit: int = 250) -> None:
    httpd, token, bound = make_server(cfg, port, limit)
    url = f"http://127.0.0.1:{bound}/?t={token}"
    print(f"{TOOL_NAME} live graph (authenticated, loopback-only):", flush=True)
    print(f"  {url}", flush=True)
    print("Open that exact URL — it carries a one-time token. Ctrl-C to stop.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()


_CSP_HEADER = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
               "img-src data:; connect-src 'self'; base-uri 'none'; form-action 'none'")
