"""
Shared CML / Cloudera AI authentication helpers.

Centralizes the repeated pattern of building CML authorization headers
and resolving the active CML token across all services.
"""
from __future__ import annotations

import os


def get_cml_token() -> str:
    """
    Resolves the active CML / Cloudera AI token from environment variables.

    Priority order:
      1. CML_TOKEN
      2. CDSW_API_KEY
      3. LITELLM_API_KEY
    """
    return (
        os.getenv("CML_TOKEN")
        or os.getenv("CDSW_API_KEY")
        or os.getenv("LITELLM_API_KEY")
        or ""
    ).strip()


def build_cml_headers(token: str | None = None, extra: dict | None = None) -> dict:
    """
    Builds the standard CML authorization headers used for cross-service
    HTTP requests. If no token is provided, it resolves one automatically.

    Returns a dict with 'Authorization' and 'X-CDSW-API-Key' headers when
    a token is available, plus any extra headers merged in.
    """
    token = token if token is not None else get_cml_token()
    headers: dict = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-CDSW-API-Key"] = token
    if extra:
        headers.update(extra)
    return headers