import os
import asyncio
import httpx
import re
import yaml
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, create_model
from crewai import Agent, Crew, Task, LLM
from crewai.tools import BaseTool
from mcp import ClientSession
from mcp.client.sse import sse_client
from shared.cml_auth import build_cml_headers

_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"

def log_ts(msg: str):
    """Prints log messages with precise millisecond timestamps."""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"⏱️ [{ts}] {msg}", flush=True)

def task_completion_callback(task_output):
    log_ts(f"✅ TASK COMPLETED: {task_output.name or 'Task'}")

def agent_step_callback(agent_action):
    if hasattr(agent_action, 'tool'):
        log_ts(f"🤖 AGENT ACTION: Triggering Tool '{agent_action.tool}'")

def load_yaml(file_name: str) -> dict:
    path = _CONFIG_DIR / file_name
    if not path.exists(): return {}
    with open(path, 'r') as f:
        return yaml.safe_load(f) or {}


# Placeholder substitution that tolerates literal braces and unknown tokens
# (unlike str.format, which raises KeyError/IndexError on them). Only known
# {key} placeholders are replaced; everything else is preserved verbatim.
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def safe_format(template: str, **values) -> str:
    def _replace(match):
        key = match.group(1)
        if key in values and values[key] is not None:
            return str(values[key])
        return match.group(0)  # unknown placeholder -> keep as-is
    return _PLACEHOLDER_RE.sub(_replace, template)


def validate_workflow_configs() -> List[str]:
    """Cross-check all YAML configs against each other and the runtime registries.
    Returns a list of human-readable configuration errors (empty when valid)."""
    errors: List[str] = []

    workflows = load_yaml("workflows.yaml")
    agents = load_yaml("agents.yaml")
    tasks = load_yaml("tasks.yaml")

    known_agents = set(agents.keys())
    known_tasks = set(tasks.keys())
    known_llms = set(LLM_REGISTRY.keys())
    known_tools = set(TOOL_REGISTRY.keys())

    # Agents: llm + tools must resolve
    for agent_name, agent_cfg in agents.items():
        llm = agent_cfg.get("llm", "GLOBAL_LLM")
        if llm not in known_llms:
            errors.append(f"agent '{agent_name}' references unknown llm '{llm}'")
        for tool_name in agent_cfg.get("tools", []):
            if tool_name not in known_tools:
                errors.append(f"agent '{agent_name}' references unknown tool '{tool_name}'")

    # Tasks: agent must resolve
    for task_name, task_cfg in tasks.items():
        agent = task_cfg.get("agent")
        if agent not in known_agents:
            errors.append(f"task '{task_name}' references unknown agent '{agent}'")

    # Workflows: tasks + retry routing must resolve
    for wf_name, wf_cfg in workflows.items():
        wf_tasks = wf_cfg.get("tasks")
        if not isinstance(wf_tasks, list) or not wf_tasks:
            errors.append(f"workflow '{wf_name}' has no non-empty 'tasks' list")
            continue
        for task_name in wf_tasks:
            if task_name not in known_tasks:
                errors.append(f"workflow '{wf_name}' references unknown task '{task_name}'")

        rbt = (wf_cfg.get("retry_logic") or {}).get("route_back_to")
        if isinstance(rbt, dict):
            for source_task, target_task in rbt.items():
                if target_task is not None and target_task not in wf_tasks:
                    errors.append(
                        f"workflow '{wf_name}' route_back_to[{source_task}] references "
                        f"unknown task '{target_task}'"
                    )
        elif rbt is not None and rbt not in wf_tasks:
            errors.append(f"workflow '{wf_name}' route_back_to references unknown task '{rbt}'")

    # LLM model name must resolve; a missing CML_MODEL_NAME silently produces a
    # broken model string like "openai/" or "openai/None".
    if not os.environ.get("CML_MODEL_NAME", "").strip():
        errors.append(
            "CML_MODEL_NAME is not set; the LLM would use a broken model name. "
            "Set CML_MODEL_NAME (CML) or map LITELLM_MODEL_NAME."
        )

    return errors


def ensure_valid_configs():
    """Fail fast at startup with a clear message when the YAML config is inconsistent."""
    errors = validate_workflow_configs()
    if errors:
        raise RuntimeError(
            "CrewAI workflow config validation failed:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

os.environ["OPENAI_API_KEY"] = os.environ.get("CML_TOKEN") or os.environ.get("LITELLM_API_KEY", "sk-default")
os.environ["OPENAI_API_BASE"] = os.environ.get("LITELLM_PROXY_URL") or os.environ.get("LITELLM_APP_URL", "")
os.environ["OPENAI_MODEL_NAME"] = f"openai/{os.environ.get('CML_MODEL_NAME', '')}"

# --- 1. PYDANTIC SCHEMAS ---
class MetricFlowQueryPayload(BaseModel):
    metrics: List[str] = Field(
        ..., 
        description="List of metric names to query, e.g. ['cai_savings_balance_sum_metric']"
    )
    group_by: List[str] = Field(
        default_factory=list, 
        description="List of entity dimensions using double-underscore notation, e.g. ['customer_id__bank_name']"
    )
    where: Optional[str] = Field(
        default=None, 
        description="Optional MetricFlow where filter string, e.g. 'metric_time__year = 2025'"
    )

# --- 2. LLM PROFILES ---
LLM_REGISTRY = {}
llm_configs = load_yaml("llm_configs.yaml")

for llm_name, llm_params in llm_configs.items():
    llm_kwargs = {
        "model": f"openai/{os.getenv('CML_MODEL_NAME', '')}",
        "base_url": os.getenv("LITELLM_PROXY_URL") or os.getenv("LITELLM_APP_URL"),
        "api_key": os.getenv("CML_TOKEN") or os.getenv("LITELLM_API_KEY"),
        "temperature": llm_params.get("temperature", 0.0),
        "max_tokens": llm_params.get("max_tokens", 4096),
    }
    
    if "extra_body" in llm_params:
        llm_kwargs["extra_body"] = llm_params["extra_body"]

    LLM_REGISTRY[llm_name] = LLM(**llm_kwargs)

# --- 3. DYNAMIC MCP TOOLS REGISTRY ---
async def call_mcp(tool_name: str, arguments: dict = None) -> str:
    start_time = datetime.now()
    log_ts(f"🔌 MCP Call Started: '{tool_name}'")
    url = f"{os.getenv('MCP_SERVER_URL', '').rstrip('/')}/sse"
    headers = build_cml_headers(os.getenv("CML_TOKEN"))
    try:
        # These context managers close the underlying SSE + HTTP connections on
        # normal exit, errors, AND cancellation, so no connections leak when a
        # job is cancelled mid-call.
        async with sse_client(
            url=url, headers=headers,
            httpx_client_factory=lambda **kw: httpx.AsyncClient(verify=False, follow_redirects=True, **kw)
        ) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                res = await session.call_tool(tool_name, arguments=arguments or {})
        content = res.content[0].text if res and res.content else ""
    except Exception as e:
        # Report MCP failures back to the agent as tool output so it can react /
        # retry instead of crashing the whole job. asyncio.CancelledError is a
        # BaseException in Py3.8+, so it is NOT caught here and still propagates.
        content = f"__MCP_ERROR__ {tool_name}: {e}"
        log_ts(f"❌ MCP Call Failed: '{tool_name}': {e}")
    finally:
        duration = (datetime.now() - start_time).total_seconds()
        log_ts(f"🏁 MCP Call Finished: '{tool_name}' (Took {duration:.2f}s)")
    return content

def create_dynamic_tool(name: str, desc: str, expected_args: list):
    """Factory function to generate CrewAI tools with STRICT schemas and tool invocation logging."""
    schema_fields = {arg_name: (str, ...) for arg_name in expected_args}
    DynamicSchema = create_model(f"{name}Schema", **schema_fields)

    class DynamicMCPTool(BaseTool):
        # name/description/args_schema are inherited pydantic fields from
        # BaseTool; the per-tool values are supplied via the constructor (which
        # IS evaluated in this function's scope). The class body never references
        # this function's locals, since a class body cannot see them.
        def _run(self, **kwargs) -> str:
            # Sync path (CrewAI calls this outside a running event loop).
            log_ts(f"🛠️ Tool Invoked: '{self.name}'")
            try:
                loop = asyncio.get_running_loop()
                return loop.run_until_complete(call_mcp(self.name, arguments=kwargs))
            except RuntimeError:
                return asyncio.run(call_mcp(self.name, arguments=kwargs))

        async def _arun(self, **kwargs) -> str:
            # Async path (used by CrewAI's kickoff_async in this service).
            log_ts(f"🛠️ Tool Invoked: '{self.name}'")
            return await call_mcp(self.name, arguments=kwargs)

    return DynamicMCPTool(name=name, description=desc, args_schema=DynamicSchema)

TOOL_REGISTRY = {}
tools_cfg = load_yaml("tools.yaml")

for t_name, t_config in tools_cfg.items():
    TOOL_REGISTRY[t_name] = create_dynamic_tool(
        name=t_name, 
        desc=t_config.get("description", ""),
        expected_args=t_config.get("args", [])
    )

# --- 4. DYNAMIC WORKFLOW ENGINE ---
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

        t_cfg = tasks_cfg[task_name]
        a_cfg = agents_cfg[t_cfg["agent"]]

        agent = Agent(
            role=a_cfg["role"],
            goal=a_cfg["goal"],
            backstory=a_cfg["backstory"],
            llm=LLM_REGISTRY[a_cfg.get("llm", "GLOBAL_LLM")],
            tools=[TOOL_REGISTRY[t] for t in a_cfg.get("tools", []) if t in TOOL_REGISTRY],
            step_callback=agent_step_callback,
            memory=False
        )

        # Correctly pass either compiled_mf_sql or sql_query to the prompt template
        active_sql = state.compiled_mf_sql if (job_type == "semantic" and task_name == "execute_sql_task") else state.sql_query

        task_desc = safe_format(
            t_cfg["description"],
            user_question=state.user_question,
            db_schema=state.db_schema,
            error_context=state.error_context,
            sql_query=active_sql
        )

        # Dynamic output schema assignment for MetricFlow payload drafting
        extra_task_args = {}
        if task_name == "mf_draft_payload_task":
            extra_task_args["output_pydantic"] = MetricFlowQueryPayload

        task = Task(
            description=task_desc,
            expected_output=t_cfg["expected_output"],
            agent=agent,
            callback=task_completion_callback,
            **extra_task_args
        )

        crew = Crew(agents=[agent], tasks=[task], verbose=True)
        result = await crew.kickoff_async()
        raw_output = result.raw

        # Internal State Mapping
        if task_name in ["fetch_schema_task", "mf_fetch_schema_task"]:
            state.db_schema = raw_output
        elif task_name == "draft_sql_task":
            state.sql_query = re.sub(r"```sql|```", "", raw_output).strip()
        elif task_name == "mf_draft_payload_task":
            if hasattr(result, "pydantic") and result.pydantic:
                state.sql_query = result.pydantic.model_dump_json()
            else:
                state.sql_query = re.sub(r"```(?:json)?|```", "", raw_output).strip()
        elif task_name == "mf_execute_task":
            state.compiled_mf_sql = raw_output
        elif task_name in ["execute_sql_task", "evaluate_policy_task"]:
            state.final_data = raw_output

        # Retry Logic Interceptor
        if retry_logic:
            err_keywords = retry_logic.get("error_keywords", [])
            if any(err in raw_output for err in err_keywords) and state.retries < retry_logic.get("max_retries", 3):
                log_ts(f"⚠️ [Flow] Error Detected! Routing back. Error: {raw_output[:50]}...")
                state.error_context = raw_output
                state.retries += 1
                # Route back to the task that should regenerate the faulty output.
                # route_back_to may be a single task name (applies to every task) or
                # a per-task mapping. If a task's target is None/unset, retry it in
                # place (bounded by max_retries) so non-recoverable errors (e.g.
                # Impala execution failures) surface instead of looping into the
                # wrong remediation context. The first task always retries in place.
                if current_task_idx > 0:
                    rbt = retry_logic.get("route_back_to")
                    route_target = rbt.get(task_name) if isinstance(rbt, dict) else rbt
                    if route_target is not None and route_target in tasks_to_run:
                        current_task_idx = tasks_to_run.index(route_target)
                continue

        state.error_context = ""
        current_task_idx += 1

    log_ts(f"🎉 Universal Execution Finished for '{job_type}'")

    final_payload = {}
    for frontend_key, state_attr in output_mapping.items():
        final_payload[frontend_key] = getattr(state, state_attr, None)
    
    return final_payload


ensure_valid_configs()
