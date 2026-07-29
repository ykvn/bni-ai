import os
import sys
from pathlib import Path

from app.core.ingest_knowledge import build_ingest_config, run_auto_ingest

# cd /home/cdsw/ask-data/backend
# python -m app.core.reindex_knowledge

def main() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    env = os.environ.copy()
    config = build_ingest_config(backend_dir=backend_dir, env=env)

    print("🔄 Re-indexing knowledge base...")
    print(f"- docs dir: {config['docs_dir']}")
    print(f"- Chroma server: {config['chroma_host']}:{config['chroma_port']}")
    print(f"- collection: {config['collection_name']}")

    run_auto_ingest(
        docs_dir=config["docs_dir"],
        chroma_host=config["chroma_host"],
        chroma_port=config["chroma_port"],
        collection_name=config["collection_name"],
    )


if __name__ == "__main__":
    main()
