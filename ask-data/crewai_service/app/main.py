import uuid
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from crewai_service.app.core import job_db

app = FastAPI(title="CrewAI Agent Microservice Engine")

class ProcessRequest(BaseModel):
    question: str

@app.on_event("startup")
def startup_event():
    job_db.init_db()

@app.get("/")
@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "CrewAI Agent Microservice"}

@app.post("/process")
def process_task(payload: ProcessRequest):
    """
    HTTP Endpoint called by REST API Gateway. Enqueues job and returns job_id in < 10ms.
    """
    user_question = payload.question.strip() if payload.question else ""
    if not user_question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    job_id = str(uuid.uuid4())
    job_info = job_db.create_job(job_id=job_id, question=user_question)

    return {
        "job_id": job_id,
        "status": job_info["status"],
        "message": "CrewAI task queued successfully."
    }

@app.get("/status/{job_id}")
def get_task_status(job_id: str):
    """
    HTTP Endpoint called by REST API Gateway to retrieve task execution status and results.
    """
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