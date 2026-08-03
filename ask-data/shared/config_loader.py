"""
Global configuration loader for the ask-data project.

Allows every service (mcp_server, backend, frontend, qdrant_server,
qwen_inference, litellm_proxy) to share a single .env file placed at
the ask-data/ root, instead of maintaining per-folder .env files.

Priority order (highest wins):
  1. Existing OS / CML Project environment variables
  2. Values loaded from the shared .env file

Why: On Cloudera AI (CML) you can set all config once as Project
Environment Variables and skip the .env entirely. Locally you can use a
single ask-data/.env as a fallback. This loader resolves both cases.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _find_project_root() -> Path:
    """
    Locates the ask-data/ project root (the folder that directly contains
    the shared/ package). Searches a comprehensive set of candidate roots
    to work whether this runs as a script, inside a notebook, or from a
    CML Application/session with any working directory.

    A candidate root is valid if it contains shared/config_loader.py.
    """
    # A root is valid when shared/config_loader.py lives directly inside it.
    def _is_root(p: Path) -> bool:
        return (p / "shared" / "config_loader.py").exists()

    cwd = Path.cwd().resolve()
    candidates: list[Path] = []

    # 1. Walk UP from CWD (covers notebooks/sessions launched inside the project)
    p = cwd
    while True:
        candidates.append(p)
        if p.parent == p:
            break
        p = p.parent

    # 2. Walk DOWN from CWD looking for the project under common names
    for name in ("ask-data", "project", "workspace"):
        candidates.append(cwd / name)

    # 3. Known CML / Cloudera AI locations (both /home/cdsw and /home/cdsw/ask-data)
    cml_parent = Path("/home/cdsw")
    candidates.append(cml_parent)
    candidates.append(cml_parent / "ask-data")

    # 4. This module's location (ask-data/shared/config_loader.py) and its parent
    base = Path(__file__).resolve()
    candidates.append(base.parent)          # ask-data/shared
    candidates.append(base.parent.parent)   # ask-data

    for candidate in candidates:
        root = candidate.resolve()
        if _is_root(root):
            return root

    # Best-effort fallback: assume this module's parent is the project root
    return base.parent.parent


_project_root_cache: Path | None = None


def get_project_root() -> Path:
    """Returns the resolved ask-data/ project root (cached)."""
    global _project_root_cache
    if _project_root_cache is None:
        _project_root_cache = _find_project_root()
    return _project_root_cache


def bootstrap(hint: str | Path | None = None) -> Path:
    """
    One-call initializer for any service entry point.

    Resolves the ask-data/ project root, adds it to sys.path (so the
    shared/ package is importable from any CWD), and loads the global
    .env into os.environ. Safe to call more than once.

    Args:
        hint: Optional path to prefer as a candidate root. When running
            as a CML Application (no __file__), pass the script's repo
            root, e.g. Path("/home/cdsw/ask-data"), or leave as None to
            rely on the built-in search.

    Returns:
        The resolved project root Path.
    """
    global _project_root_cache

    if _project_root_cache is None:
        found = _find_project_root()
        # If the automatic search fell back to a bad guess but the caller
        # supplied a hint, prefer the hint.
        if hint is not None:
            hint_path = Path(hint).resolve()
            if (hint_path / "shared" / "config_loader.py").exists():
                found = hint_path
        _project_root_cache = found

    root = _project_root_cache
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    load_project_env()
    return root


def _parse_env_file(path: Path) -> dict[str, str]:
    """
    Parses a simple KEY=VALUE .env file into a dict.

    Handles blank lines, # comments, quoted values, and inline comments.
    """
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        # Split off inline comments (only if preceded by whitespace)
        key, _, rest = line.partition("=")
        key = key.strip()
        value = rest.strip()
        # Strip surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        # Remove trailing inline comment like  KEY=value  # comment
        if " #" in value:
            value = value.split(" #", 1)[0].strip()
        if key:
            values[key] = value
    return values


def load_project_env(env_file: str | None = None) -> dict[str, str]:
    """
    Loads the single project .env file into os.environ for keys not
    already present in the current environment.

    Returns a dict of the keys that were actually injected.
    """
    if env_file is None:
        env_file = str(get_project_root() / ".env")

    env_path = Path(env_file).resolve()
    injected: dict[str, str] = {}

    if not env_path.exists():
        print(
            f"ℹ️ [config_loader] No shared .env found at {env_path}. "
            "Relying on existing environment variables only."
        )
        return injected

    parsed = _parse_env_file(env_path)
    for key, value in parsed.items():
        # Do NOT override existing OS / CML env vars — they take priority.
        if key not in os.environ:
            os.environ[key] = value
            injected[key] = value

    print(
        f"✅ [config_loader] Loaded {len(parsed)} entries from {env_path} "
        f"({len(injected)} injected into environment)."
    )
    return injected