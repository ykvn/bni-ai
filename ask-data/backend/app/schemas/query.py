# ask-data/backend/app/schemas/query.py
from typing import Literal
from pydantic import BaseModel

class QueryRequest(BaseModel):
    """Defines the strict data structure for incoming user questions"""
    question: str
    type: Literal["sql", "rag"] = "sql"
