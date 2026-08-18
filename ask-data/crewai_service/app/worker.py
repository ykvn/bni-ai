import json
import asyncio
import re
from datetime import datetime
from crewai_service.app.core import job_db
from crewai_service.app.services.agent_engine import run_universal_agent

_active_tasks: dict[str, asyncio.Task] = {}

def log_ts(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"⏱️ [{ts}] {msg}", flush=True)

def _is_cancelled(job_id: str) -> bool:
    job = job_db.get_job(job_id)
    return job is not None and job.get("status") == "cancelled"


_ROW_LIST_KEYS = ("data", "rows", "results", "result", "records")


def _extract_records(parsed) -> list:
    """Best-effort extraction of a tabular record list from parsed JSON.
    Handles a bare list of rows, a dict wrapping a list under common keys
    (data/rows/results/result/records), or a single flat row object. Returns
    an empty list for non-tabular objects (e.g. error/metadata payloads), so
    row_count is not inflated by a wrapper or error object."""
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in _ROW_LIST_KEYS:
            val = parsed.get(key)
            if isinstance(val, list):
                return val
        # A flat object of only scalar values is treated as a single row.
        if parsed and all(not isinstance(v, (dict, list)) for v in parsed.values()):
            return [parsed]
        return []
    return []

async def _process_single_job(job: dict):
    job_id = job["job_id"]
    user_question = job["question"]
    job_type = (job.get("type") or "sql").lower()
    job_start_time = datetime.now()

    try:
        log_ts(f"⚡ [Worker Engine] Starting Job {job_id} ({job_type}): '{user_question[:50]}...'")

        # 1. Call the Unified Execution Engine
        unified_payload = await run_universal_agent(job_type, user_question)

        if _is_cancelled(job_id):
            raise asyncio.CancelledError(f"Job {job_id} was cancelled by user.")

        # 2. Extract Data directly mapped from workflows.yaml
        raw_data = unified_payload.get("final_data") or ""
        agent_response = unified_payload.get("response")
        records = []

        # Parse Tabular JSON Data if it exists
        if raw_data:
            try:
                clean_json = re.sub(r"```(?:json)?|```", "", raw_data).strip()
                parsed = json.loads(clean_json)
                
                records = _extract_records(parsed)
            except (ValueError, TypeError):
                # Fallback: If it couldn't parse, treat it as conversational text
                if not agent_response:
                    agent_response = raw_data

        # 3. Assemble Frontend JSON Contract
        payload = {
            "question": user_question,
            "status": "Success",
            "type": job_type,
            "predicted_sql": unified_payload.get("predicted_sql"),
            "compiled_mf_sql": unified_payload.get("compiled_mf_sql"),
            "row_count": len(records),
            "data": records if records else None,
            "response": agent_response
        }

        job_db.update_job_status(job_id, status="completed", result=json.dumps(payload))
        total_time = (datetime.now() - job_start_time).total_seconds()
        log_ts(f"✅ [Worker Engine] Job {job_id} Completed in {total_time:.2f}s TOTAL")

    except asyncio.CancelledError:
        log_ts(f"🚫 [Worker Engine] Job {job_id} was cancelled.")
        job_db.update_job_status(job_id, status="cancelled", error="Job cancelled by user request.")
        raise
    except Exception as e:
        log_ts(f"❌ [Worker Engine Error] Task {job_id} failed: {e}")
        job_db.update_job_status(job_id, status="failed", error=str(e))

def cancel_job(job_id: str) -> bool:
    db_cancelled = job_db.cancel_job(job_id)
    task = _active_tasks.get(job_id)
    if task is not None and not task.done():
        task.cancel()
        return True
    return db_cancelled

async def run_worker_loop(max_concurrent_jobs: int = 5):
    log_ts("🤖 [Worker Engine] Starting worker loop...")
    job_db.init_db()
    semaphore = asyncio.Semaphore(max_concurrent_jobs)

    async def worker_task(job_data):
        async with semaphore:
            await _process_single_job(job_data)

    while True:
        try:
            job = job_db.claim_pending_job()
            if not job:
                await asyncio.sleep(0.5)
                continue

            job_id = job["job_id"]
            # Cancel may have raced between the claim and task creation (no task
            # exists yet for cancel_job() to find). Don't dispatch a cancelled job.
            if _is_cancelled(job_id):
                continue

            task = asyncio.create_task(worker_task(job))
            _active_tasks[job_id] = task
            task.add_done_callback(lambda fut, jid=job_id: _active_tasks.pop(jid, None))

        except Exception as e:
            log_ts(f"❌ [Worker Dispatch Error]: {e}")
            await asyncio.sleep(1.0)