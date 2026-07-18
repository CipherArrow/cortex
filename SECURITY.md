# Cortex — security model

Cortex is a **local, single-user tool**. It reads a project you already trust
enough to have on disk, writes an index beside it, and can serve a live view on
loopback. This document states what Cortex actively defends against, and — just
as importantly — what it does not, so you know the real boundaries.

## Trust boundary

The owner of the account running Cortex is trusted. The defenses below protect
that owner from **other local users**, from **malicious web pages** in the
owner's browser, and from **hostile content inside a scanned repository**. They
do not defend against an attacker who already has your user account or root.

## What is defended

### No code execution from scanned content
Cortex never executes what it scans. Python is read with `ast.parse` (parses, does
not run), other languages with regexes, and config with `tomllib`/`json` (safe
parsers — no `yaml.load`, `eval`, `exec`, `pickle`, or `subprocess` anywhere).
**Zero third-party dependencies**, so there is no supply chain to poison.

### The graph viewer cannot be turned into an attack (no injection)
Scanned text (docstrings, symbol names, headings) flows into the generated HTML
graph. That text is (a) sanitized at the model layer — control characters
stripped, whitespace collapsed, length-capped — and (b) escaped when embedded in
the page's `<script>` data block (`<`, `>`, `&`, U+2028/2029 → unicode escapes),
so a file containing `</script>…` cannot break out and inject markup or code.
The standalone/served page also ships a strict **Content-Security-Policy**
(`default-src 'none'; connect-src 'self'`) — even a hypothetical injection could
load no remote code and exfiltrate to no external host.

### The live server is authenticated and loopback-only
`cortex serve`:
- **Binds `127.0.0.1` only** — never reachable from the LAN/Wi-Fi.
- Requires an **unguessable per-run token** (`secrets.token_urlsafe`) on every
  request. The token is delivered once via the printed URL, then held in a
  cookie that is **`HttpOnly` + `SameSite=Strict`**. A malicious web page open in
  your browser cannot read the token (same-origin policy) and cannot have the
  cookie sent for it (SameSite=Strict) — this closes the classic **DNS-rebinding
  / CSRF** hole that plagues unauthenticated localhost servers.
- **Allow-lists the `Host` header** to loopback names (second line of defense vs
  rebinding) and sends **no CORS headers**, so cross-origin pages cannot read
  responses even if a request reaches the socket.
- Is **GET-only**, lists no directories, sends a neutral `Server` banner, sets
  `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options: DENY`, and a
  per-connection timeout. The token exists only in memory + the printed URL —
  nothing sensitive is written to disk.

### The index is private to you
`.cortex/` is created `0700` and its files (`graph.json`, `index.db`,
`manifest.json`, `MAP.md`, `activity.jsonl`) `0600` — **other local users cannot
read your knowledge graph or the live "what is the agent doing" feed.**

### Reads cannot escape the project
The scanner does not follow directory symlinks, and skips any **symlinked file
whose target resolves outside the project root**, so a crafted repo cannot make
Cortex slurp `/etc/shadow` into the index. `sync --changed` paths are validated
to stay within the project before being read.

### Writes are atomic and serialized
The index, graph, and manifest are written to a temp file and atomically renamed,
and concurrent writers take a per-project `flock`. A reader (or another agent)
can never observe a half-written or corrupted index — mitigating a whole class of
"interrupt mid-update" failures.

### Scanning is bounded
Files above a size cap are skipped, binary files are skipped, and per-line length
is capped before regex matching, so a pathological file cannot hang a scan.
**Only regular files are opened** — a FIFO/named pipe blocks on `open()` until a
writer appears and a character device can stream forever, so either could hang a
scan indefinitely; both are skipped (this applies to source files and to the
`CACHEDIR.TAG` probe). Self-tagged cache directories (Cache Directory Tagging
Specification) are pruned whole, so a vendored dependency tree cannot swamp the
index.

## Residual risks (honest limits)

- **Prompt injection via scanned content.** Cortex sanitizes text for *markup*
  safety, but `MAP.md` and query results still contain real content from the
  repo. Any tool that reads a codebase can be prompt-injected by hostile strings
  in that codebase; Cortex is a lens, not a filter. Treat a scanned repo's
  content with the same caution as the repo itself. This is inherent to the
  category and is not claimed to be solved.
- **No transport encryption (by design).** `cortex serve` speaks plain HTTP.
  Loopback traffic never leaves the machine and cannot be sniffed on the wire, so
  TLS on `127.0.0.1` would add certificate-management pain for no confidentiality
  gain. The token + loopback binding is the appropriate control. Do not expose the
  port off-box (e.g. via an SSH tunnel to an untrusted network) without adding TLS.
- **Same-user / root.** Anything running as your user (or root) can read `.cortex`
  and your source alike. Cortex's file permissions defend against *other* users,
  not against code already running as you.
- **Integrity vs. a local writer.** An attacker who can already write inside your
  project could tamper with `.cortex/`. Since they could equally edit your source,
  Cortex does not add cryptographic index signing — it would protect nothing that
  the source itself isn't already exposed to.

## Reporting

This is a personal tool; open an issue on the repository for anything that looks
like a real bypass of the boundaries above.
