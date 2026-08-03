from __future__ import annotations

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> str:
    """
    Locates the single global ask-data/.env configuration file.

    With the shared config_loader, env vars are already injected into
    os.environ before this module is imported. This fallback only matters
    when the module is used directly (e.g. unit tests, notebooks) and the
    loader wasn't run first.
    """
    base = Path(__file__).resolve()
    candidates = [
        base.parents[3] / ".env",   # ask-data/.env  (global shared config)
        base.parents[2] / ".env",   # mcp_server/.env (legacy fallback)
        Path.cwd() / ".env",        # Current Working Directory fallback
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Cloudera Impala Core Credentials
    impala_host: str = Field(alias="IMPALA_HOST")
    impala_port: int = Field(default=443, alias="IMPALA_PORT")
    impala_http_path: str = Field(default="cliservice", alias="IMPALA_HTTP_PATH")
    cdp_user: str = Field(alias="CDP_USER")
    cdp_pass: str = Field(alias="CDP_PASS")
    db_name: str = Field(default="default", alias="DB_NAME")

    # Standardized Qdrant & Vector Embedding Storage (Local Transformers Layer)
    # qdrant_persist_dir: str = Field(default="/home/cdsw/ask-data/qdrant_server/qdrant_db", alias="QDRANT_DATA_PATH")
    qdrant_server_url: str = Field(default="http://localhost:6333", alias="QDRANT_SERVER_URL")
    qdrant_collection: str = Field(default="bank_abc_knowledge", alias="QDRANT_COLLECTION")
    qdrant_model: str = Field(default="all-MiniLM-L6-v2", alias="QDRANT_MODEL")


settings = Settings()  # type: ignore[call-arg]