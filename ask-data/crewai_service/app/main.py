import uuid
import json
import asyncio
from typing import Literal
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from crewai_service.app.core import job_db
from crewai_service.app.worker import run_worker_loop, cancel_job

app = FastAPI(title="CrewAI Agent Microservice Engine")

class ProcessRequest(BaseModel):
    question: str
    type: Literal["sql", "rag"] = "sql"

@app.on_event("startup")
async def startup_event():
    job_db.init_db()
    # Spawns the worker loop as a non-blocking background task within FastAPI's event loop
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
    """
    Cancels a running or pending job. If the job is currently being processed
    by the worker, the underlying asyncio task is cancelled. If the job is
    still pending, it is marked as 'cancelled' so the worker loop skips it.
    """
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
