import os
import sys
import time
import json
import subprocess
from pathlib import Path

_CREWAI_DIR = Path(__file__).resolve().parent
_ASK_DATA_ROOT = _CREWAI_DIR.parent

for path in [_ASK_DATA_ROOT, _CREWAI_DIR]:
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import shared.config_loader as config_loader
config_loader.bootstrap(hint=_ASK_DATA_ROOT)

from crewai_service.app.core import job_db
from crewai_service.app.services.translator import SQLTranslationService

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

def run_worker_loop():
    print("🤖 [CrewAI Service Engine] Starting worker loop...", flush=True)
    job_db.init_db()
    translator_service = SQLTranslationService()

    while True:
        try:
            job = job_db.fetch_next_pending_job()
            if not job:
                time.sleep(1.0)
                continue

            job_id = job["job_id"]
            user_question = job["question"]

            print(f"\n⚡ [CrewAI Engine] Executing Job {job_id}: '{user_question}'", flush=True)
            job_db.update_job_status(job_id, status="processing")

            if is_policy_question(user_question):
                rag_answer = translator_service.generate_rag_answer(user_question)
                payload = _build_payload(user_question, "Success", "RAG", None, [], rag_answer)
            else:
                generated_sql = translator_service.generate_sql(user_question)

                if "CRITICAL_SECURITY_ALERT" in generated_sql:
                    payload = _build_payload(
                        user_question, "Blocked", "SQL", generated_sql, [],
                        "Security Violation: Destroy request blocked."
                    )
                else:
                    records = translator_service.run_mcp_query(generated_sql)
                    payload = _build_payload(user_question, "Success", "SQL", generated_sql, records, None)

            job_db.update_job_status(job_id, status="completed", result=json.dumps(payload))
            print(f"✅ [CrewAI Engine] Finished Job {job_id}", flush=True)

        except Exception as e:
            print(f"❌ [CrewAI Engine Error] Task failed: {e}", flush=True)
            if 'job_id' in locals():
                job_db.update_job_status(job_id, status="failed", error=str(e))
            time.sleep(2.0)

def main():
    app_port = int(os.environ.get("CDSW_APP_PORT", 8091))
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{_CREWAI_DIR}:{pythonpath}" if pythonpath else str(_CREWAI_DIR)

    # Launch HTTP Server for CrewAI Service
    api_cmd = [
        sys.executable, "-m", "uvicorn", "crewai_service.app.main:app",
        "--host", "127.0.0.1",
        "--port", str(app_port),
        "--log-level", "info"
    ]
    print(f"🌐 [CrewAI Service App] Starting HTTP REST Engine on http://127.0.0.1:{app_port}")
    api_process = subprocess.Popen(api_cmd, cwd=str(_ASK_DATA_ROOT), env=env)

    # Run Worker Loop in main thread
    try:
        run_worker_loop()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down CrewAI Service...")
        api_process.terminate()

if __name__ == "__main__":
    main()