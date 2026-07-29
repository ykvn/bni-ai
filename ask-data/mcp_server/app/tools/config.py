from __future__ import annotations

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

def _find_env_file() -> str:
    """
    Dynamically finds the .env configuration file inside the workspace context.
    Looks in mcp_server/, ask-data/, or the execution working directory handles.
    """
    # Assuming file location: mcp_server/app/tools/config.py
    base_path = Path(__file__).resolve()
    candidates = [
        base_path.parents[2] / ".env",   # mcp_server/.env
        base_path.parents[3] / ".env",   # ask-data/.env
        Path.cwd() / ".env",             # Current Working Directory fallback
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return ".env"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_find_env_file(), 
        env_file_encoding="utf-8", 
        extra="ignore"
    )

    # Cloudera Impala Core Credentials
    impala_host: str = Field(alias="IMPALA_HOST")
    impala_port: int = Field(default=443, alias="IMPALA_PORT")
    impala_http_path: str = Field(default="cliservice", alias="IMPALA_HTTP_PATH")
    cdp_user: str = Field(alias="CDP_USER")
    cdp_pass: str = Field(alias="CDP_PASS")
    db_name: str = Field(default="default", alias="DB_NAME")

    # Standardized ChromaDB & Vector Embedding Storage (Local Transformers Layer)
    chroma_persist_dir: str = Field(default="/home/cdsw/ask-data/chroma_server/chroma_db", alias="CHROMA_PERSIST_DIR")
    chroma_server_url: str = Field(default="http://localhost:8000", alias="CHROMA_SERVER_URL")
    chroma_collection: str = Field(default="bank_abc_knowledge", alias="CHROMA_COLLECTION")
    chroma_model: str = Field(default="all-MiniLM-L6-v2", alias="CHROMA_MODEL")

settings = Settings()  # type: ignore[call-arg]