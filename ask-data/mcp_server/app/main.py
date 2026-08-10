import os
import sys
import json
import anyio

from fastapi import FastAPI, Request
from starlette.routing import Mount
from fastmcp import FastMCP
from mcp.server.sse import SseServerTransport

# --- ACTIVE TOOL REGISTRATION ---
from app.tools.config import settings  
from app.tools.execute_banking_query import execute_banking_query
from app.tools.get_database_schema import get_database_schema
from app.tools.search_golden_queries import search_golden_queries
from app.tools.rag_search import search_policy_documents as perform_rag_search

# 1. Initialize the central FastMCP application state
mcp = FastMCP("Bank-ABC-Modular-Orchestrator")

# 2. Configure the standardized SSE message pipeline transport
sse = SseServerTransport("/messages")

@mcp.tool(name="get_database_schema")
async def mcp_get_database_schema(user_question: str) -> str:
    """
    Dynamically retrieves the structural enterprise schema configuration, table layouts, 
    and available columns relevant to the user's question. Use this to understand the data structure.
    """
    # ⚡ Offload the heavy search to a background thread without argument overrides
    return await anyio.to_thread.run_sync(get_database_schema, user_question)

@mcp.tool(name="search_golden_queries")
async def mcp_search_golden_queries(user_question: str) -> str:
    """
    Searches the Golden Queries database for verified, highly accurate SQL templates 
    matching the user's intent. Use this to learn complex SQL syntax (like window functions or joins).
    """
    return await anyio.to_thread.run_sync(search_golden_queries, user_question, 5, 2)

@mcp.tool(name="execute_banking_query")
def mcp_execute_banking_query(sql_query: str) -> str:
    """
    Executes a read-only Cloudera Impala SELECT statement against the live big data 
    analytics warehouse cluster and returns rows structured as a JSON string.
    """
    return execute_banking_query(sql_query)

@mcp.tool(name="search_policy_documents")
async def mcp_search_policy_documents(query: str) -> str:
    """
    Performs a semantic vector distance search against local persistent enterprise banking manuals,
    compliance guidelines, and SOP documentation (Qdrant) to return matching structural context fragments.
    """
    return await anyio.to_thread.run_sync(perform_rag_search, query, 3)

# 3. Create the FastAPI container to manage incoming enterprise cluster traffic
app = FastAPI(title="Bank ABC Production MCP Gateway")

# Route incoming protocol control packets cleanly into the SSE transport layer
app.router.routes.append(Mount("/messages", app=sse.handle_post_message))

@app.get("/")
@app.get("/health")
def platform_health_check():
    """Basic endpoint used by Cloudera AI to verify the container layer is active"""
    return {
        "status": "healthy", 
        "protocol": "Model Context Protocol v1", 
        "transport": "Server-Sent Events (SSE)"
    }

@app.get("/sse")
async def handle_sse_handshake(request: Request):
    """Establishes the long-lived protocol connection stream for incoming AI clients"""
    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp._mcp_server.run(
            streams[0], streams[1], mcp._mcp_server.create_initialization_options()
        )

# =====================================================================
# 🧪 SWAGGER DOCS INTERACTIVE TESTING ENDPOINTS
# =====================================================================

@app.get("/api/test/schema")
def test_schema_tool(user_question: str):
    """Interactive playground to test your get_database_schema tool"""
    return {"matched_schema": get_database_schema(user_question)}

@app.get("/api/test/golden_queries")
def test_golden_queries_tool(user_question: str):
    """Interactive playground to test your search_golden_queries tool"""
    return {"matched_queries": search_golden_queries(user_question)}

@app.post("/api/test/sql")
def test_sql_tool(sql_query: str):
    """Interactive playground to test your execute_banking_query tool"""
    raw_result = execute_banking_query(sql_query)
    try:
        return {"status": "success", "data": json.loads(raw_result)}
    except Exception:
        return {"status": "info_or_error", "message": raw_result}

@app.post("/api/test/rag")
def test_rag_tool(search_query: str):
    """Interactive playground to test your search_policy_documents tool"""
    raw_results = perform_rag_search(query=search_query, n_results=3)
    return {"status": "success", "matched_context": raw_results}