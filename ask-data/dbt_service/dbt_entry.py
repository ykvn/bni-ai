"""
CAI / CML Application entry point for the dbt MetricFlow & Semantic Layer Server.
Path: /home/cdsw/ask-data/dbt_service/dbt_entry.py
"""
import os
import sys
from pathlib import Path

# Resolve the ask-data root from inside dbt_service/
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

from shared.entry_utils import (
    bootstrap_service,
    resolve_service_dir,
    ensure_dependencies,
    build_pythonpath,
    launch_uvicorn,
    wait_for_process,
    resolve_port,
)

_SERVICE_NAME = "dbt_service"
_CALLER_FILE = __file__ if "__file__" in globals() else None


def trigger_dbt_preflight_checks(dbt_service_dir: Path, env: dict | None = None) -> None:
    """Pre-flight checks: Ensures dbt profiles.yml is configured for Impala CDW."""
    try:
        print("🔄 Running pre-flight dbt Semantic Layer checks...")
        
        # Ensure dbt profiles directory exists (~/.dbt/profiles.yml)
        dbt_profile_dir = Path.home() / ".dbt"
        dbt_profile_dir.mkdir(parents=True, exist_ok=True)
        profile_file = dbt_profile_dir / "profiles.yml"

        if not profile_file.exists():
            print("📝 Generating default ~/.dbt/profiles.yml for Impala...")
            impala_host = os.environ.get("IMPALA_HOST", "localhost")
            impala_port = os.environ.get("IMPALA_PORT", "443")
            impala_db = os.environ.get("DB_NAME", "test")
            impala_http_path = os.environ.get("IMPALA_HTTP_PATH", "cliservice")

            # Updated dbt profile for CDW / Port 443
            profile_content = f"""
default:
  target: dev
  outputs:
    dev:
      type: impala
      host: {impala_host}
      port: {impala_port}
      schema: {impala_db}
      auth_type: LDAP
      use_http_transport: true
      http_path: {impala_http_path}
      use_ssl: true
      threads: 1
"""
            profile_file.write_text(profile_content.strip())
            print(f"✅ Created {profile_file}")

    except Exception as e:
        print(f"⚠️ [dbt STARTUP WARNING] Bypass pre-flight check: {str(e)}")


def main() -> None:
    ask_data_root = bootstrap_service(_SERVICE_NAME)
    service_dir = resolve_service_dir(_SERVICE_NAME, ask_data_root, caller_file=_CALLER_FILE)

    if str(service_dir) not in sys.path:
        sys.path.insert(0, str(service_dir))

    app_port = resolve_port(default=8092)

    env = os.environ.copy()
    env["PYTHONPATH"] = build_pythonpath(service_dir, ask_data_root, env=env)

    ensure_dependencies(service_dir, env)

    trigger_dbt_preflight_checks(service_dir, env=env)

    process = launch_uvicorn(service_dir, "app.main:app", app_port, env)
    print(f"🌐 Starting dbt Semantic Layer Application via subprocess on http://127.0.0.1:{app_port}")

    wait_for_process(process, _SERVICE_NAME)


if __name__ == "__main__":
    main()