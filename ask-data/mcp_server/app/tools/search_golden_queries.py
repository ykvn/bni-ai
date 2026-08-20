"""
Module: search_golden_queries
================================

This module provides one small helper function, ``search_golden_queries``, used
by the MCP server to retrieve *verified* SQL templates from a Qdrant vector
database. In simple terms, it answers this question:

    "Have humans already written a trusted SQL query that matches what the
     user is asking for?"

If yes, that verified query is returned as nicely formatted text so the LLM can
use it as a reference for correct SQL syntax.

How it works (the "big picture")
--------------------------------
When the user asks a natural-language question (e.g. "What was the total sales
last quarter?"), the Golden Queries database may already contain a known-good
SQL template that someone has validated. Searching for it happens in 3 stages:

    1. VECTOR SEARCH (broad net)
       The user's question is converted into a numeric "embedding" vector and
       compared against every stored golden query in Qdrant using cosine
       similarity. This returns a *wider* pool of candidates (controlled by
       ``top_k``) because vector similarity is fast but not perfectly precise.

    2. RERANKING (narrowing it down)
       Each candidate from stage 1 is re-scored by a Cross-Encoder reranking
       model against the user's *exact* question. This is more accurate than
       plain vector similarity, so it lets us keep only the few truly relevant
       ones (controlled by ``top_n``).

    3. FORMATTING (preparing the answer)
       The top results are turned into a clean text block that can be dropped
       directly into an LLM prompt as a reference for SQL syntax.

The names of the two helper functions we call come from ``qdrant_client.py``:

- ``search_documents(query, collection_name, top_k)`` returns a list of dicts
  after querying the vector store. Each dict contains keys like ``document_id``,
  ``title``, ``excerpt``, ``page_content``, ``score`` and ``raw_payload``.
  On failure it returns a list whose first dict has an ``"error"`` key.
- ``rerank_documents(query, raw_documents, top_n)`` returns the same dicts but
  re-ordered by a Cross-Encoder relevance score (adding a ``rerank_score`` key).
"""

import os
from app.tools.qdrant_client import search_documents, rerank_documents


def search_golden_queries(user_question: str, top_k: int = 5, top_n: int = 3) -> str:
    """
    Searches the Golden Queries vector database for verified SQL templates matching the user's intent.
    Forces Cross-Encoder reranking to evaluate ONLY the 'user_intent' field.
    """
    collection_name = os.getenv("GOLDEN_COLLECTION", "bni_golden_queries")
    
    # 1. Fetch broad candidate queries using dense vector similarity
    raw_results = search_documents(query=user_question, collection_name=collection_name, top_k=top_k)
    
    if not raw_results or "error" in raw_results[0]:
        return "No verified golden queries found for this intent."

    # 2. FORCE INTENT-ONLY EVALUATION: Overwrite document text with user_intent
    for doc in raw_results:
        payload = doc.get("raw_payload", {})
        intent = payload.get("user_intent", "").strip()
        if intent:
            # Overwrite all document text fields so Cross-Encoder scores purely against intent description
            doc["page_content"] = intent
            doc["text"] = intent
            doc["excerpt"] = intent

    # 3. Re-score candidates against user_question using ONLY user_intent text
    reranked = rerank_documents(query=user_question, raw_documents=raw_results, top_n=top_n)

    # 4. Format into a clean LLM context block
    output = ["### VERIFIED GOLDEN QUERIES (Use as references for SQL syntax) ###\n"]
    for idx, doc in enumerate(reranked):
        payload = doc.get("raw_payload", {})
        intent = payload.get("user_intent", "Unknown Intent")
        sql = payload.get("sql_template", "SQL NOT FOUND")
        score = doc.get("rerank_score", doc.get("score", 0))
        
        output.append(f"-- Example {idx+1} (Relevance Score: {score}) --")
        output.append(f"Intent: {intent}")
        output.append(f"SQL:\n{sql}\n")
        
    return "\n".join(output)