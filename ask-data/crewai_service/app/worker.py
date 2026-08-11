import sys
import json
import asyncio
import re
from crewai_service.app.core import job_db
from crewai_service.app.services.agent_engine import run_sql_agent, run_rag_agent

_active_tasks: dict[str, asyncio.Task] = {}

POLICY_KEYWORDS = ("kebijakan", "sop", "prosedur", "manual", "panduan", "kriteria", "aturan", "regulasi", "dokumen", "syarat", "sk")

def is_policy_question(question: str) -> bool:
    return any(keyword in question.casefold() for keyword in POLICY_KEYWORDS)

def _is_cancelled(job_id: str) -> bool:
    job = job_db.get_job(job_id)
    return job is not None and job.get("status") == "cancelled"

async def _process_single_job(job: dict):
    job_id, user_question = job["job_id"], job["question"]

    try:
        print(f"\n⚡ [CrewAI Engine] Executing Job {job_id}: '{user_question}'", flush=True)

        if is_policy_question(user_question):
            # 1. RAG Workflow
            agent_response = await run_rag_agent(user_question)
            if _is_cancelled(job_id): raise asyncio.CancelledError()
            
            payload = {"status": "Success", "type": "RAG", "response": agent_response}
        else:
            # 2. SQL Workflow
            agent_response = await run_sql_agent(user_question)
            if _is_cancelled(job_id): raise asyncio.CancelledError()

            # Attempt to parse the LLM's output into the exact JSON your UI needs
            try:
                # Strip potential markdown blocks (```json ... ```)
                clean_json = re.sub(r"```json|```", "", agent_response).strip()
                parsed_data = json.loads(clean_json)
                payload = {
                    "status": "Success",
                    "type": "SQL",
                    "predicted_sql": parsed_data.get("predicted_sql"),
                    "data": parsed_data.get("data", [])
                }
            except json.JSONDecodeError:
                # Fallback if the agent answers conversationally instead of with JSON
                payload = {"status": "Success", "type": "Conversational", "response": agent_response}

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
    db_cancelled = job_db.cancel_job(job_id)
    task = _active_tasks.get(job_id)
    if task is not None and not task.done():
        task.cancel()
        return True
    return db_cancelled

async def run_worker_loop(max_concurrent_jobs: int = 5):
    print(f"🤖 [CrewAI Service Engine] Starting parallel worker loop...", flush=True)
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