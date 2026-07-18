"""File walking, hashing, and the incremental manifest.

The manifest records a content hash per file so `sync` can re-extract only what
changed. No git required — hashes are the change signal.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from . import MANIFEST_FILE, POINTER_FILE
from .config import EXT_LANG, Config
from .secure import within_root


def _looks_binary(path: Path) -> bool:
    """Cheap binary sniff: a NUL byte in the first 8 KiB."""
    try:
        with open(path, "rb") as fh:
            return b"\x00" in fh.read(8192)
    except OSError:
        return True


def file_hash(path: Path) -> str:
    h = hashlib.sha1()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def is_source(rel_name: str) -> bool:
    return Path(rel_name).suffix.lower() in EXT_LANG


def iter_files(cfg: Config):
    """Yield (abs_path: Path, rel_path: str) for every scannable source file."""
    root = cfg.root
    for dirpath, dirnames, filenames in os.walk(root, followlinks=cfg.follow_symlinks):
        # Prune ignored directories in place so os.walk skips them.
        dirnames[:] = [d for d in dirnames if d not in cfg.ignore_dirs]
        for fn in filenames:
            if fn == POINTER_FILE:
                continue  # Cortex's own root pointer is an output, not input
            if any(fnmatch(fn, g) for g in cfg.ignore_globs):
                continue
            if Path(fn).suffix.lower() not in EXT_LANG:
                continue
            abs_path = Path(dirpath) / fn
            # A symlinked file whose target escapes the project must not be read
            # (prevents a crafted repo from pulling in /etc/shadow etc.).
            if abs_path.is_symlink() and not within_root(abs_path, root):
                continue
            try:
                if abs_path.stat().st_size > cfg.max_file_bytes:
                    continue
            except OSError:
                continue
            if _looks_binary(abs_path):
                continue
            rel = os.path.relpath(abs_path, root).replace(os.sep, "/")
            yield abs_path, rel


@dataclass
class ManifestDiff:
    added: list = field(default_factory=list)
    changed: list = field(default_factory=list)
    removed: list = field(default_factory=list)

    @property
    def touched(self) -> list:
        return self.added + self.changed

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.changed or self.removed)


def load_manifest(cfg: Config) -> dict:
    path = cfg.data_dir / MANIFEST_FILE
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text("utf-8")).get("files", {})
    except Exception:
        return {}


def save_manifest(cfg: Config, files: dict) -> None:
    from .secure import harden_file, secure_dir
    secure_dir(cfg.data_dir)
    path = cfg.data_dir / MANIFEST_FILE
    tmp = path.with_suffix(".json.tmp")
    payload = {"version": 1, "files": files}
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), "utf-8")
    harden_file(tmp)
    os.replace(tmp, path)
    harden_file(path)


def scan_manifest(cfg: Config) -> dict:
    """Build a fresh manifest {rel: {hash, mtime, size}} from disk."""
    out = {}
    for abs_path, rel in iter_files(cfg):
        try:
            st = abs_path.stat()
        except OSError:
            continue
        out[rel] = {
            "hash": file_hash(abs_path),
            "mtime": int(st.st_mtime),
            "size": st.st_size,
        }
    return out


def diff_manifest(old: dict, new: dict) -> ManifestDiff:
    d = ManifestDiff()
    for rel, meta in new.items():
        if rel not in old:
            d.added.append(rel)
        elif old[rel].get("hash") != meta.get("hash"):
            d.changed.append(rel)
    for rel in old:
        if rel not in new:
            d.removed.append(rel)
    return d
