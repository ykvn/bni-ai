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

# Bootstrap environment variables
try:
    from shared.entry_utils import bootstrap_service
    bootstrap_service("test_runner")
except Exception:
    try:
        from dotenv import load_dotenv
        load_dotenv(_ASK_DATA_ROOT / ".env")
    except Exception:
        pass

from app.tools.search_mf_catalog import NO_MF_RESPONSE, search_mf_catalog


def run_mf_catalog_test(user_question: str):
    """Executes search_mf_catalog and displays the resulting catalog (or refusal)."""
    # STALE-DEPLOYMENT GUARD ------------------------------------------------
    # If the running machine is executing an old copy of the module (or an
    # older .pyc bytecode), it would still emit an empty `matched_*: []` YAML
    # instead of the refusal. Abort with a clear message so the outdated text
    # is never silently shown.
    _expected_refusal = "I am sorry, I don't have this information on my database."
    if NO_MF_RESPONSE != _expected_refusal:
        print("❌ STALE DEPLOYMENT DETECTED: the loaded module is NOT the latest code.")
        print(f"   Expected message: {_expected_refusal!r}")
        print(f"   Loaded message:   {NO_MF_RESPONSE!r}")
        print("   -> Clear __pycache__ caches and redeploy the updated")
        print("      ask-data/mcp_server/app/tools/search_mf_catalog.py, then re-run.")
        return

    print(f"\n🔍 Testing search_mf_catalog with query: '{user_question}'")
    print("=" * 80)

    try:
        catalog_output = search_mf_catalog(user_query=user_question)
        print(catalog_output)
    except Exception as e:
        print(f"❌ Error executing search_mf_catalog: {e}")

    print("=" * 80 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test runner for MetricFlow catalog discovery tool.")
    parser.add_argument(
        "--question",
        "-q",
        type=str,
        default="Berapa total saldo tabungan nasabah di bulan ini?",
        help="User question to test against MetricFlow catalog retrieval."
    )
    args = parser.parse_args()

    run_mf_catalog_test(user_question=args.question)