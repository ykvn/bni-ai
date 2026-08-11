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
from crewai.flow.flow import Flow, listen, start, router
from mcp import ClientSession
from mcp.client.sse import sse_client
from shared.cml_auth import build_cml_headers

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


# --- 1. GLOBAL SETUP ---
GLOBAL_LLM = LLM(
    model=f"openai/{os.getenv('CML_MODEL_NAME')}",
    base_url=os.getenv("LITELLM_PROXY_URL") or os.getenv("LITELLM_APP_URL"),
    api_key=os.getenv("CML_TOKEN") or os.getenv("LITELLM_API_KEY"),
    temperature=0.0,
    max_tokens=4096
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
            llm=GLOBAL_LLM,
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
        # Not used natively by the Flow, but kept for structural integrity
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
            llm=GLOBAL_LLM,
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


# --- 4. STATE AND FLOW ---
class SQLState(BaseModel):
    user_question: str = ""
    db_schema: str = ""  # 🚀 Renamed to avoid Pydantic conflict
    sql_query: str = ""
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
            tasks=[crew_instance.fetch_schema_task()]
        )
        result = await crew.kickoff_async(inputs={"user_question": self.state.user_question})
        self.state.db_schema = result.raw
        # No return string needed; CrewAI automatically moves to the next listener

    @listen(fetch_schema)     # Listens for Step 1 to finish
    @listen("retry_sql")      # Listens for the Router to send it back here
    async def draft_sql(self):
        log_ts(f"🌊 [Flow] Step 2: Drafting SQL (Retry: {self.state.retries})...")
        crew_instance = SQLAgentCrew()
        crew = Crew(
            agents=[crew_instance.sql_developer()],
            tasks=[crew_instance.draft_sql_task()]
        )
        result = await crew.kickoff_async(inputs={
            "user_question": self.state.user_question,
            "db_schema": self.state.db_schema,
            "error_context": self.state.error_context
        })
        import re
        self.state.sql_query = re.sub(r"```sql|```", "", result.raw).strip()

    @router(draft_sql)        # Runs immediately after Step 2
    async def execute_and_validate(self):
        log_ts("🌊 [Flow] Step 3: Executing SQL against Impala...")
        crew_instance = SQLAgentCrew()
        crew = Crew(
            agents=[crew_instance.sql_executor()],
            tasks=[crew_instance.execute_sql_task()]
        )
        result = await crew.kickoff_async(inputs={"sql_query": self.state.sql_query})
        raw_output = result.raw
        
        # CONDITIONAL ROUTING: Route back if Impala throws a syntax error
        error_keywords = ["Engine Error", "AnalysisException", "Syntax error", "ParseException"]
        if any(err in raw_output for err in error_keywords) and self.state.retries < 3:
            log_ts(f"⚠️ [Flow] Impala Error Detected! Routing back to Agent 2. Error: {raw_output[:50]}...")
            self.state.error_context = raw_output
            self.state.retries += 1
            return "retry_sql"  # Sends execution BACK to Step 2
            
        self.state.final_data = raw_output
        return "complete" 


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