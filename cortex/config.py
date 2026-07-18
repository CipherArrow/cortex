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
# extractor-key to an implementation. Coverage is tiered:
#   "python"  = stdlib ast (full fidelity)
#   "regex"   = language-specific regex rules (functions/classes/imports)
#   "generic" = conservative universal heuristic (long-tail code languages)
#   "config"  = top-level keys of data/config files
#   ""        = file node only (still searchable and part of the graph)
EXT_LANG = {
    # -- Tier 1: Python (ast) ------------------------------------------------
    ".py": ("python", "python"), ".pyi": ("python", "python"),
    ".pyw": ("python", "python"),
    # -- Tier 2: language-specific regex rules -------------------------------
    ".js": ("javascript", "regex"), ".jsx": ("javascript", "regex"),
    ".mjs": ("javascript", "regex"), ".cjs": ("javascript", "regex"),
    ".ts": ("typescript", "regex"), ".tsx": ("typescript", "regex"),
    ".mts": ("typescript", "regex"), ".cts": ("typescript", "regex"),
    ".svelte": ("svelte", "regex"), ".vue": ("vue", "regex"),
    ".astro": ("svelte", "regex"),
    ".rs": ("rust", "regex"),
    ".go": ("go", "regex"),
    ".java": ("java", "regex"),
    ".kt": ("kotlin", "regex"), ".kts": ("kotlin", "regex"),
    ".c": ("c", "regex"), ".h": ("c", "regex"),
    ".cpp": ("cpp", "regex"), ".cc": ("cpp", "regex"), ".cxx": ("cpp", "regex"),
    ".hpp": ("cpp", "regex"), ".hh": ("cpp", "regex"), ".hxx": ("cpp", "regex"),
    ".cs": ("csharp", "regex"),
    ".rb": ("ruby", "regex"),
    ".php": ("php", "regex"),
    ".sh": ("shell", "regex"), ".bash": ("shell", "regex"), ".zsh": ("shell", "regex"),
    ".swift": ("swift", "regex"),
    ".scala": ("scala", "regex"), ".sc": ("scala", "regex"),
    ".dart": ("dart", "regex"),
    ".lua": ("lua", "regex"),
    ".ex": ("elixir", "regex"), ".exs": ("elixir", "regex"),
    ".erl": ("erlang", "regex"), ".hrl": ("erlang", "regex"),
    ".hs": ("haskell", "regex"),
    ".clj": ("clojure", "regex"), ".cljs": ("clojure", "regex"), ".cljc": ("clojure", "regex"),
    ".ml": ("ocaml", "regex"), ".mli": ("ocaml", "regex"),
    ".fs": ("fsharp", "regex"), ".fsi": ("fsharp", "regex"), ".fsx": ("fsharp", "regex"),
    ".m": ("objc", "regex"), ".mm": ("objc", "regex"),
    ".groovy": ("groovy", "regex"), ".gradle": ("groovy", "regex"),
    ".ps1": ("powershell", "regex"), ".psm1": ("powershell", "regex"),
    ".pl": ("perl", "regex"), ".pm": ("perl", "regex"),
    ".r": ("r", "regex"), ".R": ("r", "regex"),
    ".jl": ("julia", "regex"),
    ".zig": ("zig", "regex"),
    ".nim": ("nim", "regex"),
    ".sol": ("solidity", "regex"),
    ".proto": ("protobuf", "regex"),
    ".graphql": ("graphql", "regex"), ".gql": ("graphql", "regex"),
    ".sql": ("sql", "regex"),
    ".tf": ("terraform", "regex"), ".tfvars": ("terraform", "regex"),
    # -- Tier 3: code long-tail via the generic heuristic --------------------
    ".cr": ("crystal", "generic"), ".vala": ("vala", "generic"),
    ".d": ("d", "generic"), ".pas": ("pascal", "generic"), ".pp": ("pascal", "generic"),
    ".f90": ("fortran", "generic"), ".f95": ("fortran", "generic"),
    ".f03": ("fortran", "generic"), ".f": ("fortran", "generic"),
    ".adb": ("ada", "generic"), ".ads": ("ada", "generic"),
    ".cob": ("cobol", "generic"), ".cbl": ("cobol", "generic"),
    ".ino": ("arduino", "generic"), ".v": ("verilog", "generic"),
    ".sv": ("systemverilog", "generic"), ".vhd": ("vhdl", "generic"),
    ".tcl": ("tcl", "generic"), ".rkt": ("racket", "generic"),
    ".elm": ("elm", "generic"), ".purs": ("purescript", "generic"),
    ".hx": ("haxe", "generic"), ".gd": ("gdscript", "generic"),
    # -- Markdown / prose ----------------------------------------------------
    ".md": ("markdown", "markdown"), ".markdown": ("markdown", "markdown"),
    ".mdx": ("markdown", "markdown"),
    ".rst": ("rst", ""), ".adoc": ("asciidoc", ""), ".org": ("org", ""),
    ".tex": ("latex", ""),
    # -- Data / config -------------------------------------------------------
    ".yaml": ("yaml", "config"), ".yml": ("yaml", "config"),
    ".toml": ("toml", "config"), ".json": ("json", "config"),
    ".jsonc": ("json", "config"), ".json5": ("json", "config"),
    ".ini": ("ini", "config"), ".cfg": ("ini", "config"), ".conf": ("ini", "config"),
    ".env": ("dotenv", "config"), ".properties": ("properties", "config"),
    ".prisma": ("prisma", ""),
    # -- Markup / styling (file node) ---------------------------------------
    ".html": ("html", ""), ".htm": ("html", ""), ".xml": ("xml", ""),
    ".css": ("css", ""), ".scss": ("scss", ""), ".sass": ("sass", ""), ".less": ("less", ""),
}

# Files with no (or an irrelevant) extension, keyed by exact basename.
SPECIAL_FILENAMES = {
    "Dockerfile": ("dockerfile", ""), "Containerfile": ("dockerfile", ""),
    "Makefile": ("make", "generic"), "GNUmakefile": ("make", "generic"),
    "makefile": ("make", "generic"), "Justfile": ("just", "generic"),
    "CMakeLists.txt": ("cmake", "generic"),
    "Gemfile": ("ruby", "regex"), "Rakefile": ("ruby", "regex"),
    "Guardfile": ("ruby", "regex"), "Vagrantfile": ("ruby", "regex"),
    "Brewfile": ("ruby", "regex"), "Podfile": ("ruby", "regex"),
    "Fastfile": ("ruby", "regex"),
    "BUILD": ("starlark", "python"), "BUILD.bazel": ("starlark", "python"),
    "WORKSPACE": ("starlark", "python"), "Tiltfile": ("starlark", "python"),
    "Procfile": ("procfile", ""),
}

# Languages whose files define a namespace and so become MODULE nodes.
MODULE_LANGS = frozenset({"python", "starlark"})


def classify(name_or_path) -> tuple[str, str]:
    """Return (language, extractor_key) for a file. Single source of truth used
    by the walker and the scanner. Checks special basenames first, then the
    extension. Unknown files return ("", "")."""
    p = Path(name_or_path)
    special = SPECIAL_FILENAMES.get(p.name)
    if special:
        return special
    return EXT_LANG.get(p.suffix.lower(), ("", ""))


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
