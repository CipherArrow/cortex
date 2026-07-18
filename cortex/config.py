"""Scan configuration: what to walk, what to skip, and how to classify files.

Defaults are sensible for mixed code+prose projects. A project may override
them with a `.cortex/config.toml` (read with stdlib tomllib).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import DATA_DIR

# Directories pruned during the walk (never descended into).
DEFAULT_IGNORE_DIRS = frozenset({
    ".git", ".hg", ".svn", DATA_DIR,
    "node_modules", ".venv", "venv", "env", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", "target", "out", ".gradle", ".svelte-kit", ".next",
    ".idea", ".cache", "cache", ".turbo", "coverage",
    "models", "checkpoints", ".unsloth",
})

# File globs skipped entirely (matched against the file name).
DEFAULT_IGNORE_GLOBS = (
    "*.lock", "*.min.js", "*.min.css", "*.map",
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.svg", "*.ico",
    "*.pdf", "*.zip", "*.gz", "*.tar", "*.7z", "*.rar",
    "*.wav", "*.mp3", "*.flac", "*.ogg", "*.mp4", "*.mov", "*.webm",
    "*.bin", "*.onnx", "*.gguf", "*.safetensors", "*.pt", "*.pth", "*.ckpt",
    "*.class", "*.jar", "*.o", "*.a", "*.so", "*.dll", "*.dylib", "*.exe",
    "*.woff", "*.woff2", "*.ttf", "*.otf",
    "*.db", "*.sqlite", "*.sqlite3",
)

# Extension -> (language, extractor-key). The extractor registry maps the
# extractor-key to an implementation.
EXT_LANG = {
    ".py": ("python", "python"),
    ".pyi": ("python", "python"),
    ".js": ("javascript", "regex"),
    ".jsx": ("javascript", "regex"),
    ".mjs": ("javascript", "regex"),
    ".cjs": ("javascript", "regex"),
    ".ts": ("typescript", "regex"),
    ".tsx": ("typescript", "regex"),
    ".svelte": ("svelte", "regex"),
    ".vue": ("vue", "regex"),
    ".rs": ("rust", "regex"),
    ".go": ("go", "regex"),
    ".java": ("java", "regex"),
    ".kt": ("kotlin", "regex"),
    ".c": ("c", "regex"),
    ".h": ("c", "regex"),
    ".cpp": ("cpp", "regex"),
    ".cc": ("cpp", "regex"),
    ".hpp": ("cpp", "regex"),
    ".cs": ("csharp", "regex"),
    ".rb": ("ruby", "regex"),
    ".php": ("php", "regex"),
    ".sh": ("shell", "regex"),
    ".md": ("markdown", "markdown"),
    ".markdown": ("markdown", "markdown"),
    ".mdx": ("markdown", "markdown"),
    ".yaml": ("yaml", "config"),
    ".yml": ("yaml", "config"),
    ".toml": ("toml", "config"),
    ".json": ("json", "config"),
}

# .py files become module nodes; everything else is a plain file node.
MODULE_LANGS = frozenset({"python"})


@dataclass
class Config:
    root: Path
    ignore_dirs: frozenset = DEFAULT_IGNORE_DIRS
    ignore_globs: tuple = DEFAULT_IGNORE_GLOBS
    max_file_bytes: int = 1_500_000       # skip files larger than this
    max_symbols_per_file_in_map: int = 12  # keep MAP.md scannable
    max_map_files_per_dir: int = 200
    follow_symlinks: bool = False

    @property
    def data_dir(self) -> Path:
        return self.root / DATA_DIR


def load_config(root: str | Path) -> Config:
    """Build a Config for `root`, applying `.cortex/config.toml` overrides."""
    root = Path(root).resolve()
    cfg = Config(root=root)
    cfg_path = root / DATA_DIR / "config.toml"
    if cfg_path.is_file():
        try:
            data = tomllib.loads(cfg_path.read_text("utf-8"))
        except Exception:
            return cfg
        scan = data.get("scan", {})
        extra_dirs = set(scan.get("ignore_dirs", []))
        if extra_dirs:
            cfg.ignore_dirs = frozenset(cfg.ignore_dirs | extra_dirs)
        extra_globs = tuple(scan.get("ignore_globs", []))
        if extra_globs:
            cfg.ignore_globs = cfg.ignore_globs + extra_globs
        if "max_file_bytes" in scan:
            cfg.max_file_bytes = int(scan["max_file_bytes"])
        if "max_symbols_per_file_in_map" in scan:
            cfg.max_symbols_per_file_in_map = int(scan["max_symbols_per_file_in_map"])
    return cfg


DEFAULT_CONFIG_TOML = """\
# Cortex scan configuration. Delete any line to fall back to the built-in default.
[scan]
# Extra directory names to skip (added to the built-in ignore list).
ignore_dirs = []
# Extra file globs to skip.
ignore_globs = []
# Files larger than this many bytes are skipped.
max_file_bytes = 1500000
# How many symbols to list per file in MAP.md (the rest stay queryable in the index).
max_symbols_per_file_in_map = 12
"""
