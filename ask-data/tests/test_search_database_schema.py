import argparse
import sys
from pathlib import Path

# Ensure root directory is importable
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

# Import the schema search tool function
try:
    from app.tools.schema_utils import search_database_schema
except ImportError:
    # Fallback if imported from local module in the same folder
    from schema_utils import search_database_schema


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