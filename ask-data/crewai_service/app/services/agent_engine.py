import os
import httpx
import re
import yaml
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel
from crewai import Agent, Crew, Task, LLM
from crewai.tools import tool
from mcp import ClientSession
from mcp.client.sse import sse_client
from shared.cml_auth import build_cml_headers

_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"

def log_ts(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"⏱️ [{ts}] {msg}", flush=True)

def task_completion_callback(task_output):
    log_ts(f"✅ TASK COMPLETED: {task_output.name or 'Task'}")

def agent_step_callback(agent_action):
    if hasattr(agent_action, 'tool'):
        log_ts(f"🤖 AGENT ACTION: Triggering Tool '{agent_action.tool}'")

os.environ["OPENAI_API_KEY"] = os.environ.get("CML_TOKEN") or os.environ.get("LITELLM_API_KEY", "sk-default")
os.environ["OPENAI_API_BASE"] = os.environ.get("LITELLM_PROXY_URL") or os.environ.get("LITELLM_APP_URL", "")
os.environ["OPENAI_MODEL_NAME"] = f"openai/{os.environ.get('CML_MODEL_NAME', '')}"

# --- 1. LLM PROFILES ---
LLM_REGISTRY = {
    "GLOBAL_LLM": LLM(
        model=f"openai/{os.getenv('CML_MODEL_NAME')}",
        base_url=os.getenv("LITELLM_PROXY_URL") or os.getenv("LITELLM_APP_URL"),
        api_key=os.getenv("CML_TOKEN") or os.getenv("LITELLM_API_KEY"),
        temperature=0.0,
        max_tokens=4096,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}}
    ),
    "REASONING_LLM": LLM(
        model=f"openai/{os.getenv('CML_MODEL_NAME')}",
        base_url=os.getenv("LITELLM_PROXY_URL") or os.getenv("LITELLM_APP_URL"),
        api_key=os.getenv("CML_TOKEN") or os.getenv("LITELLM_API_KEY"),
        temperature=0.0,
        max_tokens=4096
    )
}

# --- 2. MCP TOOLS ---
async def call_mcp(tool_name: str, arguments: dict = None) -> str:
    start_time = datetime.now()
    log_ts(f"🔌 MCP Call Started: '{tool_name}'")
    url = f"{os.getenv('MCP_SERVER_URL', '').rstrip('/')}/sse"
    headers = build_cml_headers(os.getenv("CML_TOKEN"))
    async with sse_client(
        url=url, headers=headers, 
        httpx_client_factory=lambda **kw: httpx.AsyncClient(verify=False, follow_redirects=True, **kw)
    ) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            res = await session.call_tool(tool_name, arguments=arguments or {})
            duration = (datetime.now() - start_time).total_seconds()
            log_ts(f"🏁 MCP Call Completed: '{tool_name}' (Took {duration:.2f}s)")
            return res.content[0].text if res and res.content else ""

@tool("get_database_schema")
async def mcp_get_database_schema(user_question: str) -> str:
    return await call_mcp("get_database_schema", {"user_question": user_question})

@tool("search_golden_queries")
async def mcp_search_golden_queries(user_question: str) -> str:
    return await call_mcp("search_golden_queries", {"user_question": user_question})

@tool("execute_banking_query")
async def mcp_execute_banking_query(sql_query: str) -> str:
    return await call_mcp("execute_banking_query", {"sql_query": sql_query})

@tool("search_policy_documents")
async def mcp_search_policy_documents(query: str) -> str:
    return await call_mcp("search_policy_documents", {"query": query})

@tool("search_mf_catalog")
async def mcp_search_mf_catalog(user_question: str) -> str:
    return await call_mcp("search_mf_catalog", {"user_question": user_question})

@tool("compile_mf_sql")
async def mcp_compile_mf_sql(json_payload: str) -> str:
    return await call_mcp("compile_mf_sql", {"json_payload": json_payload})

TOOL_REGISTRY = {
    "get_database_schema": mcp_get_database_schema,
    "search_golden_queries": mcp_search_golden_queries,
    "execute_banking_query": mcp_execute_banking_query,
    "search_policy_documents": mcp_search_policy_documents,
    "search_mf_catalog": mcp_search_mf_catalog,
    "compile_mf_sql": mcp_compile_mf_sql
}

# --- 3. DYNAMIC WORKFLOW ENGINE ---
def load_yaml(file_name: str) -> dict:
    with open(_CONFIG_DIR / file_name, 'r') as f:
        return yaml.safe_load(f)

class UniversalState(BaseModel):
    user_question: str = ""
    db_schema: str = ""
    sql_query: str = ""
    compiled_mf_sql: str = ""
    error_context: str = ""
    final_data: str = ""
    retries: int = 0

async def run_universal_agent(job_type: str, user_question: str) -> dict:
    log_ts(f"🚀 Universal Execution Initiated for '{job_type}'")
    
    workflows = load_yaml("workflows.yaml")
    agents_cfg = load_yaml("agents.yaml")
    tasks_cfg = load_yaml("tasks.yaml")
    
    workflow = workflows.get(job_type)
    if not workflow:
        raise ValueError(f"Unknown workflow type: {job_type}")

    state = UniversalState(user_question=user_question)
    tasks_to_run = workflow["tasks"]
    retry_logic = workflow.get("retry_logic")
    output_mapping = workflow.get("output_mapping", {})

    current_task_idx = 0
    while current_task_idx < len(tasks_to_run):
        task_name = tasks_to_run[current_task_idx]
        log_ts(f"🌊 [Flow] Executing Task: {task_name} (Retry: {state.retries})")

        # Instantiate dynamic Agent
        t_cfg = tasks_cfg[task_name]
        a_cfg = agents_cfg[t_cfg["agent"]]

        agent = Agent(
            role=a_cfg["role"],
            goal=a_cfg["goal"],
            backstory=a_cfg["backstory"],
            llm=LLM_REGISTRY[a_cfg.get("llm", "GLOBAL_LLM")],
            tools=[TOOL_REGISTRY[t] for t in a_cfg.get("tools", [])],
            step_callback=agent_step_callback,
            memory=False
        )

        # Interpolate variables into prompt
        task_desc = t_cfg["description"].format(
            user_question=state.user_question,
            db_schema=state.db_schema,
            error_context=state.error_context,
            sql_query=state.sql_query
        )

        task = Task(
            description=task_desc,
            expected_output=t_cfg["expected_output"],
            agent=agent,
            callback=task_completion_callback
        )

        # Run Task
        crew = Crew(agents=[agent], tasks=[task], verbose=True)
        result = await crew.kickoff_async()
        raw_output = result.raw

        # Internal State Mapping routing
        if task_name in ["fetch_schema_task", "mf_fetch_schema_task"]:
            state.db_schema = raw_output
        elif task_name in ["draft_sql_task", "mf_draft_payload_task"]:
            state.sql_query = re.sub(r"```(?:sql|json)?|```", "", raw_output).strip()
        elif task_name == "mf_execute_task":
            state.compiled_mf_sql = raw_output
        elif task_name in ["execute_sql_task", "evaluate_policy_task"]:
            state.final_data = raw_output

        # Retry Logic Interceptor
        if retry_logic and current_task_idx > 0:
            err_keywords = retry_logic.get("error_keywords", [])
            if any(err in raw_output for err in err_keywords) and state.retries < retry_logic.get("max_retries", 3):
                log_ts(f"⚠️ [Flow] Error Detected! Routing back. Error: {raw_output[:50]}...")
                state.error_context = raw_output
                state.retries += 1
                current_task_idx = tasks_to_run.index(retry_logic["route_back_to"])
                continue

        state.error_context = ""
        current_task_idx += 1

    log_ts(f"🎉 Universal Execution Finished for '{job_type}'")

    # Map to final payload according to workflows.yaml
    final_payload = {}
    for frontend_key, state_attr in output_mapping.items():
        final_payload[frontend_key] = getattr(state, state_attr, None)
    
    return final_payload