import sys
import json
import asyncio
from crewai_service.app.core import job_db
from crewai_service.app.services.translator import SQLTranslationService, SQLGeneratedSuccess

# Module-level registry of in-flight asyncio tasks, keyed by job_id.
# This allows the cancel endpoint to cancel a running task directly.
_active_tasks: dict[str, asyncio.Task] = {}

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


def _is_cancelled(job_id: str) -> bool:
    """Checks the DB to see if the job has been marked as 'cancelled'."""
    job = job_db.get_job(job_id)
    return job is not None and job.get("status") == "cancelled"


async def _process_single_job(job: dict, translator_service: SQLTranslationService):
    """Executes a single job independently in its own async task context."""
    job_id = job["job_id"]
    user_question = job["question"]

    try:
        print(f"\n⚡ [CrewAI Engine] Executing Job {job_id}: '{user_question}'", flush=True)

        if is_policy_question(user_question):
            rag_answer = await translator_service.generate_rag_answer(user_question)
            if _is_cancelled(job_id):
                raise asyncio.CancelledError(f"Job {job_id} was cancelled by user.")
            payload = _build_payload(user_question, "Success", "RAG", None, [], rag_answer)
        else:
            try:
                generated_sql = await translator_service.generate_sql(user_question)
                if _is_cancelled(job_id):
                    raise asyncio.CancelledError(f"Job {job_id} was cancelled by user.")

                if "CRITICAL_SECURITY_ALERT" in generated_sql:
                    payload = _build_payload(
                        user_question, "Blocked", "SQL", generated_sql, [],
                        "Security Violation: Destroy request blocked."
                    )
                else:
                    records = await translator_service.run_mcp_query(generated_sql)
                    if _is_cancelled(job_id):
                        raise asyncio.CancelledError(f"Job {job_id} was cancelled by user.")
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

    except asyncio.CancelledError:
        print(f"🚫 [CrewAI Engine] Job {job_id} was cancelled.", flush=True)
        job_db.update_job_status(job_id, status="cancelled", error="Job cancelled by user request.")
        raise
    except Exception as e:
        print(f"❌ [CrewAI Engine Error] Task {job_id} failed: {e}", flush=True)
        job_db.update_job_status(job_id, status="failed", error=str(e))


def cancel_job(job_id: str) -> bool:
    """
    Attempts to cancel a running or pending job.
    - If the job is still 'pending' (not yet picked up by the worker), it is
      marked as 'cancelled' in the DB so the worker loop will skip it.
    - If the job is 'processing' (an asyncio task is actively running), the
      task is cancelled directly via asyncio.Task.cancel().
    Returns True if the job was found and a cancellation was initiated,
    False if the job was not found or already in a terminal state.
    """
    # First, try to mark the job as cancelled in the DB (handles pending jobs)
    db_cancelled = job_db.cancel_job(job_id)

    # If the job is currently processing, also cancel the asyncio task
    task = _active_tasks.get(job_id)
    if task is not None and not task.done():
        task.cancel()
        return True

    return db_cancelled


async def run_worker_loop(max_concurrent_jobs: int = 5):
    """Non-blocking worker loop that processes multiple pending jobs in parallel."""
    print(f"🤖 [CrewAI Service Engine] Starting parallel worker loop (Max Concurrency: {max_concurrent_jobs})...", flush=True)
    job_db.init_db()
    translator_service = SQLTranslationService()
    
    # Limits maximum simultaneous LLM/MCP executions to prevent system overload
    semaphore = asyncio.Semaphore(max_concurrent_jobs)

    async def worker_task(job_data):
        async with semaphore:
            await _process_single_job(job_data, translator_service)

    while True:
        try:
            job = job_db.fetch_next_pending_job()
            if not job:
                await asyncio.sleep(0.5)
                continue

            # Instantly update status in DB so another worker loop iteration won't pick it up
            job_id = job["job_id"]
            job_db.update_job_status(job_id, status="processing")

            # Fire and forget: Launch job in background without blocking the queue loop
            task = asyncio.create_task(worker_task(job))
            _active_tasks[job_id] = task

            # Clean up the task reference once it completes (success, failure, or cancellation)
            def _cleanup(fut: asyncio.Task, jid: str = job_id):
                _active_tasks.pop(jid, None)

            task.add_done_callback(_cleanup)

        except Exception as e:
            print(f"❌ [CrewAI Engine Dispatch Error]: {e}", flush=True)
            await asyncio.sleep(1.0)
