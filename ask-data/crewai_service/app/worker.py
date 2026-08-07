import sys
import json
import asyncio
from crewai_service.app.core import job_db
from crewai_service.app.services.translator import SQLTranslationService, SQLGeneratedSuccess

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
    """Asynchronous background worker loop executed natively inside FastAPI's event loop."""
    print("🤖 [CrewAI Service Engine] Starting worker loop...", flush=True)
    job_db.init_db()
    translator_service = SQLTranslationService()

    while True:
        # Keep stream hygiene in case third-party loggers modify stdout
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

        try:
            job = job_db.fetch_next_pending_job()
            if not job:
                await asyncio.sleep(1.0)
                continue

            job_id = job["job_id"]
            user_question = job["question"]

            print(f"\n⚡ [CrewAI Engine] Executing Job {job_id}", flush=True)
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
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__