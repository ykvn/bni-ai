import uuid
import json
import asyncio
import yaml
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from crewai_service.app.core import job_db
from crewai_service.app.worker import run_worker_loop, cancel_job

app = FastAPI(title="CrewAI Agent Microservice Engine")

_WORKFLOWS_PATH = Path(__file__).resolve().parent.parent / "config" / "workflows.yaml"


def _known_workflow_types() -> set:
    """Workflow types supported by the agent engine, driven by workflows.yaml."""
    if not _WORKFLOWS_PATH.exists():
        return set()
    with open(_WORKFLOWS_PATH, "r") as f:
        data = yaml.safe_load(f) or {}
    return set(data.keys())


class ProcessRequest(BaseModel):
    question: str
    type: str = "sql"  # ✅ Changed from Literal to str for future-proof workflow types

@app.on_event("startup")
async def startup_event():
    job_db.init_db()
    asyncio.create_task(run_worker_loop())

@app.get("/")
@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "CrewAI Agent Microservice"}

@app.post("/process")
def process_task(payload: ProcessRequest):
    user_question = payload.question.strip() if payload.question else ""
    if not user_question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    known_types = _known_workflow_types()
    if known_types and payload.type not in known_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown job type '{payload.type}'. Supported types: {sorted(known_types)}"
        )

    job_id = str(uuid.uuid4())
    job_info = job_db.create_job(job_id=job_id, question=user_question, qtype=payload.type)

    return {
        "job_id": job_id,
        "status": job_info["status"],
        "message": "CrewAI task queued successfully."
    }

@app.get("/status/{job_id}")
def get_task_status(job_id: str):
    job = job_db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job ID not found.")

    result_data = None
    if job["result"]:
        try:
            result_data = json.loads(job["result"])
        except Exception:
            result_data = job["result"]

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "data": result_data,
        "error": job["error"]
    }

@app.delete("/cancel/{job_id}")
def cancel_task(job_id: str):
    cancelled = cancel_job(job_id)
    if not cancelled:
        job = job_db.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job ID not found.")
        raise HTTPException(
            status_code=409,
            detail=f"Job cannot be cancelled. Current status: '{job['status']}'."
        )
    return {"job_id": job_id, "status": "cancelled", "message": "Job cancellation requested."}