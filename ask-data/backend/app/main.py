import os
import httpx
from fastapi import FastAPI, HTTPException
from app.schemas.query import QueryRequest

app = FastAPI(title="Bank ABC NL-to-SQL Core API Gateway")

CREWAI_SERVICE_URL = os.getenv("CREWAI_SERVICE_URL", "").rstrip("/")
CML_TOKEN = (
    os.getenv("CML_TOKEN")
).strip()


def _get_httpx_client() -> httpx.Client:
    """
    HTTPX client pre-configured with CML authorization headers for cross-application HTTP requests.
    """
    headers = {}
    if CML_TOKEN:
        headers["Authorization"] = f"Bearer {CML_TOKEN}"
        headers["X-CDSW-API-Key"] = CML_TOKEN

    return httpx.Client(
        headers=headers,
        verify=False,
        follow_redirects=True,
        timeout=10.0
    )


@app.get("/")
@app.get("/health")
def health_check():
    return {"status": "healthy", "gateway": "operational", "target_crewai": CREWAI_SERVICE_URL}


@app.post("/ask")
def ask_ai(payload: QueryRequest):
    """
    Proxies user query to Standalone CrewAI Microservice over HTTP with CML Authentication.
    """
    user_question = payload.question.strip() if payload.question else ""
    if not user_question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    try:
        with _get_httpx_client() as client:
            resp = client.post(f"{CREWAI_SERVICE_URL}/process", json={"question": user_question})
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=f"CrewAI Service error: {resp.text}")
            return resp.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"CrewAI Microservice unreachable: {str(e)}")


@app.get("/job/{job_id}")
def get_job_status(job_id: str):
    """
    Proxies job status request to Standalone CrewAI Microservice over HTTP with CML Authentication.
    """
    try:
        with _get_httpx_client() as client:
            resp = client.get(f"{CREWAI_SERVICE_URL}/status/{job_id}")
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=f"Job query error: {resp.text}")
            return resp.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"CrewAI Microservice unreachable: {str(e)}")