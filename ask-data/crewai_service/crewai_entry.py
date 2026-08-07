import os
import sys
import asyncio
import json
import subprocess
import threading
from pathlib import Path

# 1. Resolve Root Directory
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

import shared.config_loader as config_loader
config_loader.bootstrap(hint=_ASK_DATA_ROOT)


# 2. Resolve Service Directory
def _resolve_crewai_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    return _ASK_DATA_ROOT / "crewai_service"


CREWAI_DIR = _resolve_crewai_dir()
if str(CREWAI_DIR) not in sys.path:
    sys.path.insert(0, str(CREWAI_DIR))

# 3. Imports after path registration
from crewai_service.app.core import job_db
from crewai_service.app.services.translator import SQLTranslationService, SQLGeneratedSuccess # Import custom exception

POLICY_KEYWORDS = (
    "kebijakan", "sop", "prosedur", "manual", "panduan", "kriteria",
    "aturan", "regulasi", "dokumen", "syarat", "sk", "surat keputusan"
)


def is_policy_question(question: str) -> bool:
    return any(keyword in question.casefold() for keyword in POLICY_KEYWORDS)


def _build_payload(question: str, status: str, response_type: str, predicted_sql=None, records=None, response=None):
    normalized_records = records or []
    return {
        "question": question,
        "status": status,
        "type": response_type,
        "predicted_sql": predicted_sql,
        "row_count": len(normalized_records),
        "data": normalized_records,
        "response": response,
    }


async def run_worker_loop():
    print("🤖 [CrewAI Service Engine] Starting worker loop...", flush=True)
    job_db.init_db()
    translator_service = SQLTranslationService()

    while True:
        # Force restore standard output stream in case CrewAI's rich console left it hijacked
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

        try:
            job = job_db.fetch_next_pending_job()
            if not job:
                await asyncio.sleep(1.0)
                continue

            job_id = job["job_id"]
            user_question = job["question"]

            print(f"\n⚡ [bold][[CrewAI Engine]][/bold] Executing Job {job_id}", flush=True)
            job_db.update_job_status(job_id, status="processing")

            if is_policy_question(user_question):
                rag_answer = await translator_service.generate_rag_answer(user_question)
                payload = _build_payload(user_question, "Success", "RAG", None, [], rag_answer)
            else:
                try:
                    generated_sql = await translator_service.generate_sql(user_question)

                    if "CRITICAL_SECURITY_ALERT" in generated_sql:
                        payload = _build_payload(
                            user_question, "Blocked", "SQL", generated_sql, [],
                            "Security Violation: Destroy request blocked."
                        )
                    else:
                        records = await translator_service.run_mcp_query(generated_sql)
                        payload = _build_payload(user_question, "Success", "SQL", generated_sql, records, None)
                        
                except SQLGeneratedSuccess as e:
                    payload = _build_payload(
                        question=user_question, 
                        status="Success", 
                        response_type="SQL", 
                        predicted_sql=e.sql, 
                        records=e.records, 
                        response=None
                    )

            job_db.update_job_status(job_id, status="completed", result=json.dumps(payload))
            print(f"✅ [CrewAI Engine] Finished Job {job_id}", flush=True)

        except Exception as e:
            print(f"❌ [CrewAI Engine Error] Task failed: {e}", flush=True)
            if 'job_id' in locals():
                job_db.update_job_status(job_id, status="failed", error=str(e))
            await asyncio.sleep(2.0)
        finally:
            # Always ensure terminal stdout is clean for the next job iteration
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__


def _start_worker_thread():
    """Runs the async worker loop in a dedicated thread with an isolated event loop."""
    asyncio.run(run_worker_loop())


def main():
    app_port = int(os.environ.get("CDSW_APP_PORT", 8091))
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{CREWAI_DIR}:{pythonpath}" if pythonpath else str(CREWAI_DIR)

    # Launch HTTP Server for CrewAI Service
    api_cmd = [
        sys.executable, "-m", "uvicorn", "crewai_service.app.main:app",
        "--host", "127.0.0.1",
        "--port", str(app_port),
        "--log-level", "warning"
    ]
    print(f"🌐 [CrewAI Service App] Starting HTTP REST Engine on [http://127.0.0.1](http://127.0.0.1):{app_port}")
    api_process = subprocess.Popen(api_cmd, cwd=str(_ASK_DATA_ROOT), env=env)

    # Launch Worker Engine in a dedicated background thread to prevent loop collisions
    worker_thread = threading.Thread(target=_start_worker_thread, daemon=True)
    worker_thread.start()

    try:
        api_process.wait()
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Shutting down CrewAI Service...")
    finally:
        if api_process.poll() is None:
            print("🧹 Terminating Uvicorn process...")
            api_process.terminate()


if __name__ == "__main__":
    main()