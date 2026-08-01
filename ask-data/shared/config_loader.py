"""
Global configuration loader for the ask-data project.

Allows every service (mcp_server, backend, frontend, chroma_server,
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
from pathlib import Path


def _find_project_root() -> Path:
    """
    Locates the ask-data/ project root by walking up from this module's
    location (ask-data/shared/config_loader.py).
    """
    # File location: ask-data/shared/config_loader.py
    base = Path(__file__).resolve()
    candidates = [
        base.parent,         # ask-data/shared
        base.parent.parent,  # ask-data
        Path.cwd(),          # current working directory fallback
    ]
    for folder in candidates:
        # Treat the folder containing this file (shared/) and its parent
        # (ask-data/) as candidate roots for project_folder structure
        for root in (folder, folder.parent):
            if (root / "shared" / "config_loader.py").exists():
                return root
    return base.parent.parent  # best-effort: assume ask-data/


_project_root_cache: Path | None = None


def get_project_root() -> Path:
    """Returns the resolved ask-data/ project root (cached)."""
    global _project_root_cache
    if _project_root_cache is None:
        _project_root_cache = _find_project_root()
    return _project_root_cache


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