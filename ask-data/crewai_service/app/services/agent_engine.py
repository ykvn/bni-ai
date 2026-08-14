import os
import httpx
import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel
from crewai import Agent, Crew, Task, LLM
from crewai.project import CrewBase, agent, crew, task
from crewai.process import Process
from crewai.tools import tool
from crewai.flow.flow import Flow, listen, start, router, or_
from mcp import ClientSession
from mcp.client.sse import sse_client
from shared.cml_auth import build_cml_headers

from pydantic import BaseModel, Field
from typing import List, Optional

_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"

# --- TIMESTAMP HELPER ---
def log_ts(msg: str):
    """Prints log messages with precise millisecond timestamps."""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"⏱️ [{ts}] {msg}", flush=True)

# --- CREWAI CALLBACKS ---
def task_completion_callback(task_output):
    log_ts(f"✅ TASK COMPLETED: {task_output.name or 'Task'}")

def agent_step_callback(agent_action):
    if hasattr(agent_action, 'tool'):
        log_ts(f"🤖 AGENT ACTION: Triggering Tool '{agent_action.tool}'")

os.environ["OPENAI_API_KEY"] = os.environ.get("CML_TOKEN") or os.environ.get("LITELLM_API_KEY", "sk-default")
os.environ["OPENAI_API_BASE"] = os.environ.get("LITELLM_PROXY_URL") or os.environ.get("LITELLM_APP_URL", "")
os.environ["OPENAI_MODEL_NAME"] = f"openai/{os.environ.get('CML_MODEL_NAME', '')}"

# --- 1. GLOBAL SETUP ---
# GLOBAL_LLM: Fast execution profile with thinking disabled (Ideal for schema lookups & query execution)
GLOBAL_LLM = LLM(
    model=f"openai/{os.getenv('CML_MODEL_NAME')}",
    base_url=os.getenv("LITELLM_PROXY_URL") or os.getenv("LITELLM_APP_URL"),
    api_key=os.getenv("CML_TOKEN") or os.getenv("LITELLM_API_KEY"),
    temperature=0.0,
    max_tokens=4096,
    extra_body={
        "chat_template_kwargs": {"enable_thinking": False}
    }
)

# REASONING_LLM: Profile with thinking enabled (Ideal for complex SQL drafting & reasoning)
REASONING_LLM = LLM(
    model=f"openai/{os.getenv('CML_MODEL_NAME')}",
    base_url=os.getenv("LITELLM_PROXY_URL") or os.getenv("LITELLM_APP_URL"),
    api_key=os.getenv("CML_TOKEN") or os.getenv("LITELLM_API_KEY"),
    temperature=0.0,
    max_tokens=4096
)

# Pydantic schema for MetricFlow JSON payload validation
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

async def call_mcp(tool_name: str, arguments: dict = None) -> str:
    start_time = datetime.now()
    log_ts(f"🔌 MCP Call Started: '{tool_name}'")
    
    url = f"{os.getenv('MCP_SERVER_URL', '').rstrip('/')}/sse"
    headers = build_cml_headers(os.getenv("CML_TOKEN"))
    
    async with sse_client(
        url=url, 
        headers=headers, 
        httpx_client_factory=lambda **kw: httpx.AsyncClient(verify=False, follow_redirects=True, **kw)
    ) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            res = await session.call_tool(tool_name, arguments=arguments or {})
            duration = (datetime.now() - start_time).total_seconds()
            log_ts(f"🏁 MCP Call Completed: '{tool_name}' (Took {duration:.2f}s)")
            return res.content[0].text if res and res.content else ""


# --- 2. CREWAI MCP TOOLS ---
@tool("get_database_schema")
async def mcp_get_database_schema(user_question: str) -> str:
    """CRITICAL FIRST STEP: Retrieves table names and columns based on the user query."""
    log_ts(f"🛠️ Tool Invoked: 'get_database_schema' | Input: {user_question[:60]}...")
    return await call_mcp("get_database_schema", {"user_question": user_question})

@tool("search_golden_queries")
async def mcp_search_golden_queries(user_question: str) -> str:
    """Searches verified SQL templates matching the user's intent."""
    log_ts(f"🛠️ Tool Invoked: 'search_golden_queries'")
    return await call_mcp("search_golden_queries", {"user_question": user_question})

@tool("execute_banking_query")
async def mcp_execute_banking_query(sql_query: str) -> str:
    """Executes Impala SQL. Returns raw JSON rows or an error message if syntax is wrong."""
    log_ts(f"🛠️ Tool Invoked: 'execute_banking_query'")
    return await call_mcp("execute_banking_query", {"sql_query": sql_query})

@tool("search_policy_documents")
async def mcp_search_policy_documents(query: str) -> str:
    """Searches enterprise banking manuals, SOPs, and compliance guidelines."""
    log_ts(f"🛠️ Tool Invoked: 'search_policy_documents'")
    return await call_mcp("search_policy_documents", {"query": query})

@tool("search_mf_catalog")
async def mcp_search_mf_catalog(user_question: str) -> str:
    """
    Searches the dbt MetricFlow semantic catalog for relevant metrics and dimensions based on the user's question.
    ALWAYS use this before drafting a MetricFlow JSON payload to retrieve the exact metric names and dimension paths.
    """
    log_ts(f"🛠️ Tool Invoked: 'search_mf_catalog'")
    return await call_mcp("search_mf_catalog", {"user_question": user_question})

@tool("compile_mf_sql")
async def mcp_compile_mf_sql(json_payload: str) -> str:
    """
    Sends a JSON query payload to the dbt MetricFlow API to compile into SQL.
    The payload MUST be a valid JSON string containing "metrics" and "group_by" arrays.
    """
    log_ts(f"🛠️ Tool Invoked: 'compile_mf_sql'")
    return await call_mcp("compile_mf_sql", {"json_payload": json_payload})


# --- 3. CREWBASE CLASSES ---
@CrewBase
class SQLAgentCrew:
    agents_config = str(_CONFIG_DIR / "agents.yaml")
    tasks_config = str(_CONFIG_DIR / "tasks.yaml")

    @agent
    def schema_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config['schema_analyst'],
            llm=GLOBAL_LLM,
            tools=[mcp_get_database_schema, mcp_search_golden_queries],
            step_callback=agent_step_callback
        )

    @agent
    def sql_developer(self) -> Agent:
        return Agent(
            config=self.agents_config['sql_developer'],
            llm=REASONING_LLM,
            tools=[],
            step_callback=agent_step_callback
        )

    @agent
    def sql_executor(self) -> Agent:
        return Agent(
            config=self.agents_config['sql_executor'],
            llm=GLOBAL_LLM,
            tools=[mcp_execute_banking_query],
            step_callback=agent_step_callback
        )

    @task
    def fetch_schema_task(self) -> Task:
        return Task(
            config=self.tasks_config['fetch_schema_task'],
            agent=self.schema_analyst(),
            callback=task_completion_callback
        )

    @task
    def draft_sql_task(self) -> Task:
        return Task(
            config=self.tasks_config['draft_sql_task'],
            agent=self.sql_developer(),
            callback=task_completion_callback
        )

    @task
    def execute_sql_task(self) -> Task:
        return Task(
            config=self.tasks_config['execute_sql_task'],
            agent=self.sql_executor(),
            callback=task_completion_callback
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=[self.schema_analyst(), self.sql_developer(), self.sql_executor()],
            tasks=[self.fetch_schema_task(), self.draft_sql_task(), self.execute_sql_task()],
            process=Process.sequential,
            verbose=True
        )


@CrewBase
class RAGAgentCrew:
    agents_config = str(_CONFIG_DIR / "agents.yaml")
    tasks_config = str(_CONFIG_DIR / "tasks.yaml")

    @agent
    def compliance_officer(self) -> Agent:
        return Agent(
            config=self.agents_config['compliance_officer'],
            llm=REASONING_LLM,
            tools=[mcp_search_policy_documents]
        )

    @task
    def evaluate_policy_task(self) -> Task:
        return Task(
            config=self.tasks_config['evaluate_policy_task'],
            agent=self.compliance_officer()
        )

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, verbose=True)


@CrewBase
class MetricFlowAgentCrew:
    agents_config = str(_CONFIG_DIR / "agents.yaml")
    tasks_config = str(_CONFIG_DIR / "tasks.yaml")

    @agent
    def mf_schema_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config['mf_schema_analyst'],
            llm=GLOBAL_LLM,
            tools=[mcp_search_mf_catalog],
            step_callback=agent_step_callback,
            memory=False
        )

    @agent
    def mf_payload_developer(self) -> Agent:
        return Agent(
            config=self.agents_config['mf_payload_developer'],
            llm=REASONING_LLM,
            tools=[],
            step_callback=agent_step_callback,
            memory=False
        )

    @agent
    def mf_executor(self) -> Agent:
        return Agent(
            config=self.agents_config['mf_executor'],
            llm=GLOBAL_LLM,
            tools=[mcp_compile_mf_sql],
            step_callback=agent_step_callback,
            memory=False
        )

    @task
    def mf_fetch_schema_task(self) -> Task:
        return Task(config=self.tasks_config['mf_fetch_schema_task'], agent=self.mf_schema_analyst(), callback=task_completion_callback)

    @task
    def mf_draft_payload_task(self) -> Task:
        return Task(
            config=self.tasks_config['mf_draft_payload_task'],
            agent=self.mf_payload_developer(),
            output_pydantic=MetricFlowQueryPayload,
            callback=task_completion_callback
        )

    @task
    def mf_execute_task(self) -> Task:
        return Task(config=self.tasks_config['mf_execute_task'], agent=self.mf_executor(), callback=task_completion_callback)

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=[self.mf_schema_analyst(), self.mf_payload_developer(), self.mf_executor()],
            tasks=[self.mf_fetch_schema_task(), self.mf_draft_payload_task(), self.mf_execute_task()],
            process=Process.sequential, verbose=True
        )

# --- 4. STATE AND FLOW ---
class SQLState(BaseModel):
    user_question: str = ""
    db_schema: str = ""
    sql_query: str = ""
    compiled_mf_sql: str = "" # Stores intermediate compiled SQL
    error_context: str = ""
    final_data: str = ""
    retries: int = 0

class SQLGenerationFlow(Flow[SQLState]):
    @start()
    async def fetch_schema(self):
        log_ts("🌊 [Flow] Step 1: Fetching Schema...")
        crew_instance = SQLAgentCrew()
        crew = Crew(
            agents=[crew_instance.schema_analyst()],
            tasks=[crew_instance.fetch_schema_task()],
            verbose=True
        )
        result = await crew.kickoff_async(inputs={"user_question": self.state.user_question})
        self.state.db_schema = result.raw

    @listen(or_(fetch_schema, "retry_sql"))
    async def draft_sql(self):
        log_ts(f"🌊 [Flow] Step 2: Drafting SQL (Retry: {self.state.retries})...")
        crew_instance = SQLAgentCrew()
        crew = Crew(
            agents=[crew_instance.sql_developer()],
            tasks=[crew_instance.draft_sql_task()],
            verbose=True
        )
        result = await crew.kickoff_async(inputs={
            "user_question": self.state.user_question,
            "db_schema": self.state.db_schema,
            "error_context": self.state.error_context
        })
        import re
        self.state.sql_query = re.sub(r"```sql|```", "", result.raw).strip()

    @router(draft_sql)
    async def execute_and_validate(self):
        log_ts("🌊 [Flow] Step 3: Executing SQL against Impala...")
        crew_instance = SQLAgentCrew()
        crew = Crew(
            agents=[crew_instance.sql_executor()],
            tasks=[crew_instance.execute_sql_task()],
            verbose=True
        )
        result = await crew.kickoff_async(inputs={"sql_query": self.state.sql_query})
        raw_output = result.raw
        
        error_keywords = ["Engine Error", "AnalysisException", "Syntax error", "ParseException"]
        if any(err in raw_output for err in error_keywords) and self.state.retries < 3:
            log_ts(f"⚠️ [Flow] Impala Error Detected! Routing back to Agent 2. Error: {raw_output[:50]}...")
            self.state.error_context = raw_output
            self.state.retries += 1
            return "retry_sql"
            
        self.state.final_data = raw_output
        return "complete"

class MetricFlowGenerationFlow(Flow[SQLState]):
    @start()
    async def mf_fetch_schema(self):
        log_ts("🌊 [MF Flow] Step 1: Fetching MetricFlow Catalog...")
        crew_inst = MetricFlowAgentCrew()
        crew = Crew(agents=[crew_inst.mf_schema_analyst()], tasks=[crew_inst.mf_fetch_schema_task()], verbose=True)
        result = await crew.kickoff_async(inputs={"user_question": self.state.user_question})
        self.state.db_schema = result.raw

    @listen(or_(mf_fetch_schema, "retry_mf"))
    async def mf_draft_payload(self):
        log_ts(f"🌊 [MF Flow] Step 2: Drafting JSON Payload (Retry: {self.state.retries})...")
        crew_inst = MetricFlowAgentCrew()
        crew = Crew(agents=[crew_inst.mf_payload_developer()], tasks=[crew_inst.mf_draft_payload_task()], verbose=True)
        result = await crew.kickoff_async(inputs={
            "user_question": self.state.user_question,
            "db_schema": self.state.db_schema,
            "error_context": self.state.error_context
        })
        
        if hasattr(result, "pydantic") and result.pydantic:
            self.state.sql_query = result.pydantic.model_dump_json()
        else:
            self.state.sql_query = re.sub(r"```(?:json)?|```", "", result.raw).strip()
            
        log_ts(f"📦 Validated Payload Prepared: {self.state.sql_query}")

    @router(mf_draft_payload)
    async def mf_compile_sql(self):
        log_ts("🌊 [MF Flow] Step 3: Compiling JSON into Impala SQL...")
        crew_inst = MetricFlowAgentCrew()
        crew = Crew(agents=[crew_inst.mf_executor()], tasks=[crew_inst.mf_execute_task()], verbose=True)
        result = await crew.kickoff_async(inputs={"sql_query": self.state.sql_query})
        raw_output = result.raw
        
        # 🔁 Retry mechanism intact for compilation failures
        error_keywords = ["MetricFlow API Error", "Syntax error", "Failed", "ERROR:"]
        if any(err in raw_output for err in error_keywords) and self.state.retries < 3:
            log_ts(f"⚠️ [MF Flow] Compilation Error Detected! Routing back to Developer (Retry {self.state.retries + 1})...")
            self.state.error_context = raw_output
            self.state.retries += 1
            return "retry_mf"
            
        self.state.compiled_mf_sql = raw_output
        return "execute_impala"

    @listen("execute_impala")
    async def mf_execute_impala(self):
        log_ts("🌊 [MF Flow] Step 4: Executing Compiled SQL against Impala...")
        
        # 🚀 REUSING THE STANDARD SQL EXECUTOR AGENT
        sql_crew_inst = SQLAgentCrew()
        crew = Crew(
            agents=[sql_crew_inst.sql_executor()], 
            tasks=[sql_crew_inst.execute_sql_task()], 
            verbose=True
        )
        
        result = await crew.kickoff_async(inputs={"sql_query": self.state.compiled_mf_sql})
        self.state.final_data = result.raw

# --- 5. EXPOSED ASYNC WORKFLOWS ---
async def run_sql_agent(user_question: str):
    log_ts("🚀 SQLGenerationFlow Execution Initiated")
    flow = SQLGenerationFlow()
    flow.state.user_question = user_question
    
    await flow.kickoff_async()
    log_ts("🎉 SQLGenerationFlow Execution Finished")
    return flow.state

async def run_rag_agent(user_question: str) -> str:
    log_ts("🚀 RAGAgentCrew Execution Initiated")
    result = await RAGAgentCrew().crew().kickoff_async(inputs={"user_question": user_question})
    log_ts("🎉 RAGAgentCrew Execution Finished")
    return str(result)

async def run_metricflow_agent(user_question: str):
    log_ts("🚀 MetricFlowGenerationFlow Execution Initiated")
    flow = MetricFlowGenerationFlow()
    flow.state.user_question = user_question
    await flow.kickoff_async()
    log_ts("🎉 MetricFlowGenerationFlow Execution Finished")
    return flow.state