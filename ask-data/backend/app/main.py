import sys
from fastapi import FastAPI, HTTPException

from app.schemas.query import QueryRequest
from app.services.translator import SQLTranslationService

app = FastAPI(title="Bank ABC NL-to-SQL Core API Gateway")
translator_service = SQLTranslationService()

POLICY_KEYWORDS = (
    "kebijakan", "sop", "prosedur", "manual", "panduan", "kriteria",
    "aturan", "regulasi", "dokumen", "syarat", "sk", "surat keputusan"
)


def is_policy_question(question: str) -> bool:
    """Heuristic Intent Classifier: Evaluates keywords to route to RAG vs SQL."""
    return any(keyword in question.casefold() for keyword in POLICY_KEYWORDS)


def _build_response(question: str, status: str, response_type: str, predicted_sql, records=None, response=None):
    """Create a consistent API payload for both SQL and RAG execution paths."""
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


# =====================================================================
# 🌐 UNIFIED HEALTH CHECKS & HTTP ENDPOINTS
# =====================================================================

@app.get("/")
@app.get("/health")
def health_check():
    """Satisfies platform container health checks."""
    return {"status": "healthy", "gateway": "operational"}


@app.post("/ask")
def ask_ai(payload: QueryRequest):
    """Processes natural language questions and routes them appropriately."""
    try:
        user_question = payload.question

        # 📑 PATH B: Document / Policy / SOP Intent Detected (Qdrant RAG)
        if is_policy_question(user_question):
            print("📚 Policy Inquiry Intercepted. Triggering RAG Strategy...")
            rag_answer = translator_service.generate_rag_answer(user_question)
            return _build_response(user_question, "Success", "RAG", None, [], rag_answer)

        # 📊 PATH A: Analytical Data / Metrics Intent Detected (Impala Text-to-SQL)
        print("📊 Analytical Query Intercepted. Initializing Agent Loop...")
        generated_sql = translator_service.generate_sql(user_question)

        # Programmatic intercept if the security guardrail gets tripped by CrewAI
        if "CRITICAL_SECURITY_ALERT" in generated_sql:
            return _build_response(
                user_question,
                "Blocked",
                "SQL",
                generated_sql,
                [],
                "Security Violation: This destructive request was terminated by system guardrails."
            )

        # Fetch records via the MCP server protocol stream
        records = translator_service.run_mcp_query(generated_sql)
        return _build_response(user_question, "Success", "SQL", generated_sql, records, None)
        
    except Exception as e:
        print(f"❌ Core API Router Processing Failure: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Gateway Processing Failure: {str(e)}"
        )