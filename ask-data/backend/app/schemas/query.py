# ask-data/backend/app/schemas/query.py
from pydantic import BaseModel

class QueryRequest(BaseModel):
    """Defines the strict data structure for incoming user questions"""
    question: str