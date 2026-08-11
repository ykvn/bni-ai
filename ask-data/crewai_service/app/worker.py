import sys
import json
import asyncio
import re
from crewai_service.app.core import job_db

# 🚀 IMPORT YOUR @CrewBase WORKFLOWS HERE
from crewai_service.app.services.agent_engine import run_sql_agent, run_rag_agent

# Module-level registry of active tasks for cancellation support
_active_tasks: dict[str, asyncio.Task] = {}

POLICY_KEYWORDS = (
    "kebijakan", "sop", "prosedur", "manual", "panduan", "kriteria",
    "aturan", "regulasi", "dokumen", "syarat", "sk", "surat keputusan"
)

def is_policy_question(question: str) -> bool:
    return any(keyword in question.casefold() for keyword in POLICY_KEYWORDS)

def _is_cancelled(job_id: str) -> bool:
    job = job_db.get_job(job_id)
    return job is not None and job.get("status") == "cancelled"

async def _process_single_job(job: dict):
    """Executes a single job independently in its own async task context."""
    job_id = job["job_id"]
    user_question = job["question"]

    try:
        print(f"\n⚡ [CrewAI Engine] Executing Job {job_id}: '{user_question}'", flush=True)

        if is_policy_question(user_question):
            # --- 1. RUN RAG AGENT WORKFLOW ---
            agent_response = await run_rag_agent(user_question)
            if _is_cancelled(job_id):
                raise asyncio.CancelledError(f"Job {job_id} was cancelled by user.")

            payload = {
                "question": user_question,
                "status": "Success",
                "type": "RAG",
                "predicted_sql": None,
                "row_count": 0,
                "data": [],
                "response": agent_response
            }
        else:
            # --- 2. RUN SQL AGENT WORKFLOW ---
            # Returns a CrewOutput object now!
            agent_result = await run_sql_agent(user_question)
            if _is_cancelled(job_id):
                raise asyncio.CancelledError(f"Job {job_id} was cancelled by user.")

            # Attempt to parse the resulting Pydantic object
            try:
                if hasattr(agent_result, 'pydantic') and agent_result.pydantic:
                    # CrewAI successfully mapped the LLM output to our SQLResultSchema
                    sql_data = agent_result.pydantic.dict()
                    predicted_sql = sql_data.get("predicted_sql", "")
                    records = sql_data.get("data", [])
                else:
                    raise ValueError("Pydantic output is missing from CrewResult.")

                payload = {
                    "question": user_question,
                    "status": "Success",
                    "type": "SQL",
                    "predicted_sql": predicted_sql,
                    "row_count": len(records),
                    "data": records,
                    "response": None
                }
            except Exception as parse_err:
                # Fallback if agent fails to adhere to Pydantic structure
                payload = {
                    "question": user_question,
                    "status": "Success",
                    "type": "Conversational",
                    "predicted_sql": None,
                    "row_count": 0,
                    "data": [],
                    "response": str(agent_result)
                }

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
    """Cancels pending jobs in DB or actively running asyncio tasks."""
    db_cancelled = job_db.cancel_job(job_id)
    task = _active_tasks.get(job_id)
    if task is not None and not task.done():
        task.cancel()  # Aborts LLM execution immediately
        return True
    return db_cancelled


async def run_worker_loop(max_concurrent_jobs: int = 5):
    """Non-blocking worker loop processing pending jobs in parallel."""
    print(f"🤖 [CrewAI Service Engine] Starting worker loop...", flush=True)
    job_db.init_db()
    semaphore = asyncio.Semaphore(max_concurrent_jobs)

    async def worker_task(job_data):
        async with semaphore:
            await _process_single_job(job_data)

    while True:
        try:
            job = job_db.fetch_next_pending_job()
            if not job:
                await asyncio.sleep(0.5)
                continue

            job_id = job["job_id"]
            job_db.update_job_status(job_id, status="processing")

            task = asyncio.create_task(worker_task(job))
            _active_tasks[job_id] = task
            task.add_done_callback(lambda fut, jid=job_id: _active_tasks.pop(jid, None))

        except Exception as e:
            print(f"❌ [CrewAI Engine Dispatch Error]: {e}", flush=True)
            await asyncio.sleep(1.0)