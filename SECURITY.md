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
**Zero third-party dependencies at runtime**, so there is no supply chain to
poison — and CI fails the build if the installed distribution's `Requires:` ever
stops being empty, so the claim cannot rot quietly into being untrue. (Building a
wheel from source uses `setuptools`, as any Python build does; installing a built
wheel pulls nothing.)

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
`manifest.json`, `MAP.md`, `graph.html`, `activity.jsonl`) `0600` — **other local
users cannot read your knowledge graph or the live "what is the agent doing" feed.**

**Exports are the deliberate exception.** `cortex graph -o PATH` writes where you
point it, at your umask, because an export exists to be opened, committed, or
published — inheriting `0600` would make it useless for that. The exported file
carries the same material as the index (file paths, symbol names, docstring
summaries), so treat `-o` as *"publish this"*: if you only want to look at the
graph, the default `.cortex/graph.html` stays owner-only, and `cortex serve` never
writes it to disk at all.

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

## Supported versions

Cortex is developed on `main`, and that is the only branch that receives fixes.
There are no third-party dependencies, so there is no dependency-patch stream to
track — updating means pulling the latest `main`.

## Reporting a vulnerability

**Please report privately first**, via GitHub's *Report a vulnerability* button
on the repository's Security tab (private security advisory). That opens a
channel visible only to the maintainer, so a real bypass isn't published before
there is a fix. Please don't open a public issue for a suspected vulnerability.

Useful in a report: which boundary above is crossed, the steps to reproduce, and
what an attacker gains. A proof-of-concept repo or file is ideal, since most of
the interesting surface is "hostile content in a scanned project."

**In scope:** anything that breaks a guarantee in *What is defended* — code
execution from scanned content, injection into the graph viewer, reading files
outside the project root, reaching `cortex serve` without the token or from
off-box, index corruption from concurrent writes, or `.cortex/` becoming
world-readable.

**Not vulnerabilities** (documented above as accepted limits): prompt-injection
via scanned repository content, the absence of TLS on a loopback-only socket,
and anything requiring an attacker who already runs code as your user or root.

This is a personal project maintained in spare time — expect a best-effort
response rather than a guaranteed SLA.
