import argparse
import sys
from pathlib import Path

# Set up ask-data root and mcp_server paths
_TESTS_DIR = Path(__file__).resolve().parent
_ASK_DATA_ROOT = _TESTS_DIR.parent
_MCP_SERVER_DIR = _ASK_DATA_ROOT / "mcp_server"

for path in [_ASK_DATA_ROOT, _MCP_SERVER_DIR]:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Bootstrap environment variables from ask-data/.env into os.environ
try:
    from shared.entry_utils import bootstrap_service
    bootstrap_service("test_runner")
except Exception:
    try:
        from dotenv import load_dotenv
        load_dotenv(_ASK_DATA_ROOT / ".env")
    except Exception:
        pass

from app.tools.search_database_schema import search_database_schema


def test_no_schema_detection():
    """Offline regression test (no network) for the no-relevant-schema guard."""
    from app.tools.search_database_schema import (
        _has_no_tables,
        NO_SCHEMA_RESPONSE,
        NO_RELEVANT_SCHEMA,
    )

    empty_schema = "database_type: Cloudera Impala\ntables: []\n"
    markered_schema = (
        "database_type: Cloudera Impala\ntables: []\nerror: NO_RELEVANT_SCHEMA\n"
    )
    populated_schema = (
        "database_type: Cloudera Impala\n"
        "tables:\n"
        "  - name: tbl\n"
        "    description: x\n"
        "    columns:\n"
        "      - name: id\n"
    )

    assert _has_no_tables(empty_schema) is True, "empty tables list should count as no schema"
    assert _has_no_tables(markered_schema) is True, "NO_RELEVANT_SCHEMA marker should count as no schema"
    assert _has_no_tables(populated_schema) is False, "populated schema should NOT count as no schema"
    assert "tables: []" not in NO_SCHEMA_RESPONSE, "refusal must not leak an empty tables block"
    assert "I am sorry, I don't have this information." in NO_SCHEMA_RESPONSE
    assert NO_RELEVANT_SCHEMA in NO_SCHEMA_RESPONSE

    print("✅ test_no_schema_detection PASSED")


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
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run offline unit checks only (no network / vector DB required)."
    )
    args = parser.parse_args()

    if args.check:
        test_no_schema_detection()
    else:
        run_schema_test(user_question=args.question)