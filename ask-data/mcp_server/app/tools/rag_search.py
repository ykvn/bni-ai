from __future__ import annotations

from app.tools.config import settings
from app.tools.qdrant_client import search_documents


def search_policy_documents(query: str, n_results: int = 3) -> str:
    """Searches the enterprise knowledge base for policy documents via Qdrant."""
    results = search_documents(query, settings.qdrant_collection, top_k=n_results)

    if results and "error" in results[0]:
        return f"Error: {results[0]['error']}"
    if not results:
        return "No matching context found in the knowledge base."

    # Format back to string for CrewAI
    return "\n\n---\n\n".join(r["excerpt"] for r in results)