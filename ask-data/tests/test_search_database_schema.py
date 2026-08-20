import argparse
import sys
from pathlib import Path

# Add ask-data root and mcp_server directory to Python path
_TESTS_DIR = Path(__file__).resolve().parent
_ASK_DATA_ROOT = _TESTS_DIR.parent
_MCP_SERVER_DIR = _ASK_DATA_ROOT / "mcp_server"

for path in [_ASK_DATA_ROOT, _MCP_SERVER_DIR]:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Import search_database_schema from mcp_server/app/tools
try:
    from app.tools.search_database_schema import search_database_schema
except ImportError:
    from mcp_server.app.tools.search_database_schema import search_database_schema


def run_schema_test(user_question: str):
    """Executes search_database_schema and displays the resulting schema YAML."""
    print(f"\n🔍 Testing search_database_schema with query: '{user_question}'")
    print("=" * 80)

    try:
        schema_output = search_database_schema(user_question=user_question)
        print(schema_output)
    except Exception as e:
        print(f"❌ Error executing search_database_schema: {e}")

    print("=" * 80 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test runner for database schema discovery tool.")
    parser.add_argument(
        "--question",
        "-q",
        type=str,
        default="Berapa rata rata nilai cash out di bulan Agustus 2026 ?",
        help="User question to test against schema retrieval."
    )
    args = parser.parse_args()

    run_schema_test(user_question=args.question)