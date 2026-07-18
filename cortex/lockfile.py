"""Per-project write lock so concurrent agents' scans/syncs serialize.

Readers (query/context/...) never take the lock — they read the last complete
index, which stays valid because writes land via atomic replace. Only writers
(scan/sync) serialize here. POSIX flock; on platforms without fcntl the lock
degrades to a no-op rather than failing.
"""

from __future__ import annotations

import contextlib

from .config import Config


@contextlib.contextmanager
def project_lock(cfg: Config):
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.data_dir / ".lock"
    try:
        import fcntl
    except ImportError:
        yield
        return
    with open(path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)   # blocks until the other writer finishes
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
