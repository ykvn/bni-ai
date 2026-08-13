import os
import sys
import json
import yaml
import anyio
import httpx
from shared.cml_auth import build_cml_headers
from app.tools.search_mf_catalog import search_mf_catalog

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
from app.tools.search_mf_catalog import search_mf_catalog
from app.tools.compile_mf_sql import compile_mf_sql
import anyio

# 1. Initialize central FastMCP application state
mcp = FastMCP("Bank Negara Indonesia Modular MCP Server")

# 2. Configure SSE message transport
sse = SseServerTransport("/messages")


# --- CLEAN SCHEMA FOR AGENTIC FLOW ---
def clean_schema_yaml(raw_yaml_str: str) -> str:
    """Strips internal reranking score fields so the LLM receives clean YAML schema without confusion."""
    try:
        data = yaml.safe_load(raw_yaml_str)
        if isinstance(data, dict) and "tables" in data:
            for table in data["tables"]:
                table.pop("score", None)
                for col in table.get("columns", []):
                    col.pop("score", None)
        return yaml.dump(data, sort_keys=False, default_flow_style=False)
    except Exception:
        return raw_yaml_str


# =====================================================================
# 🛠️ AGENTIC MCP TOOLS
# =====================================================================

@mcp.tool(name="get_database_schema")
async def mcp_get_database_schema(user_question: str) -> str:
    """
    CRITICAL FIRST STEP FOR SQL: Dynamically retrieves table names, column layouts, 
    data types, and descriptions relevant to the user's question. Always call this tool 
    BEFORE writing any SQL query to ensure exact table and column matches.
    """
    raw_schema = await anyio.to_thread.run_sync(get_database_schema, user_question)
    return clean_schema_yaml(raw_schema)


@mcp.tool(name="search_golden_queries")
async def mcp_search_golden_queries(user_question: str) -> str:
    """
    Searches the Golden Queries database for verified SQL templates matching the user's intent. 
    Use this to learn complex Impala SQL syntax, joins, and window functions.
    """
    return await anyio.to_thread.run_sync(search_golden_queries, user_question, 5, 2)


@mcp.tool(name="execute_banking_query")
def mcp_execute_banking_query(sql_query: str) -> str:
    """
    Executes a read-only Cloudera Impala SELECT statement against the analytics warehouse.
    If the query fails due to a syntax error, this tool returns the error message. 
    Use the error details to fix your query and call this tool again.
    """
    return execute_banking_query(sql_query)


@mcp.tool(name="search_policy_documents")
async def mcp_search_policy_documents(query: str) -> str:
    """
    Searches enterprise banking manuals, SOPs, and compliance policy guidelines (Qdrant).
    Use this when answering non-SQL questions regarding business rules, limits, or procedures.
    """
    return await anyio.to_thread.run_sync(perform_rag_search, query, 3)


@mcp.tool(name="search_mf_catalog")
async def mcp_search_mf_catalog(user_question: str) -> str:
    """
    Searches the MetricFlow semantic catalog for relevant metrics and dimensions.
    ALWAYS use this before writing a MetricFlow JSON query to get the exact metric names.
    """
    raw_catalog = await anyio.to_thread.run_sync(search_mf_catalog, user_question)
    return raw_catalog


@mcp.tool(name="compile_mf_sql")
async def mcp_compile_mf_sql(json_payload: str) -> str:
    """
    Sends a JSON payload to the dbt MetricFlow API to compile into SQL.
    Returns the SQL string. It DOES NOT execute the query.
    """
    return await compile_mf_sql(json_payload)


# =====================================================================
# FASTAPI SERVER CONTAINER
# =====================================================================

app = FastAPI(title="Bank Negara Indonesia MCP Gateway")
app.router.routes.append(Mount("/messages", app=sse.handle_post_message))

@app.get("/")
@app.get("/health")
def platform_health_check():
    return {
        "status": "healthy", 
        "protocol": "Model Context Protocol v1", 
        "transport": "Server-Sent Events (SSE)"
    }

@app.get("/sse")
async def handle_sse_handshake(request: Request):
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
    return {"matched_schema": get_database_schema(user_question)}

@app.get("/api/test/golden_queries")
def test_golden_queries_tool(user_question: str):
    return {"matched_queries": search_golden_queries(user_question)}

@app.post("/api/test/sql")
def test_sql_tool(sql_query: str):
    raw_result = execute_banking_query(sql_query)
    try:
        return {"status": "success", "data": json.loads(raw_result)}
    except Exception:
        return {"status": "info_or_error", "message": raw_result}

@app.post("/api/test/rag")
def test_rag_tool(search_query: str):
    raw_results = perform_rag_search(query=search_query, n_results=3)
    return {"status": "success", "matched_context": raw_results}