import os
import httpx
from pathlib import Path

from crewai import Agent, Crew, Task, LLM
from crewai.project import CrewBase, agent, crew, task
from crewai.process import Process
from crewai.tools import tool
from mcp import ClientSession
from mcp.client.sse import sse_client
from shared.cml_auth import build_cml_headers

_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"

# --- 1. GLOBAL SETUP ---
GLOBAL_LLM = LLM(
    model=f"openai/{os.getenv('CML_MODEL_NAME')}",
    base_url=os.getenv("LITELLM_PROXY_URL") or os.getenv("LITELLM_APP_URL"),
    api_key=os.getenv("CML_TOKEN") or os.getenv("LITELLM_API_KEY"),
    temperature=0.0
)

async def call_mcp(tool_name: str, arguments: dict = None) -> str:
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
            return res.content[0].text if res and res.content else ""


# --- 2. CREWAI MCP TOOLS ---
@tool("get_database_schema")
async def mcp_get_database_schema(user_question: str) -> str:
    """CRITICAL FIRST STEP: Retrieves table names and columns based on the user query."""
    print(f"\n🛠️ [AGENT ACTION] LLM triggered 'get_database_schema' with: {user_question}", flush=True)
    return await call_mcp("get_database_schema", {"user_question": user_question})

@tool("search_golden_queries")
async def mcp_search_golden_queries(user_question: str) -> str:
    """Searches verified SQL templates matching the user's intent."""
    print(f"\n🛠️ [AGENT ACTION] LLM triggered 'search_golden_queries' with: {user_question}", flush=True)
    return await call_mcp("search_golden_queries", {"user_question": user_question})

@tool("execute_banking_query")
async def mcp_execute_banking_query(sql_query: str) -> str:
    """Executes Impala SQL. Returns raw JSON rows or an error message if syntax is wrong."""
    print(f"\n🛠️ [AGENT ACTION] LLM triggered 'execute_banking_query' with SQL:\n{sql_query}", flush=True)
    return await call_mcp("execute_banking_query", {"sql_query": sql_query})

@tool("search_policy_documents")
async def mcp_search_policy_documents(query: str) -> str:
    """Searches enterprise banking manuals, SOPs, and compliance guidelines."""
    print(f"\n🛠️ [AGENT ACTION] LLM triggered 'search_policy_documents' with: {query}", flush=True)
    return await call_mcp("search_policy_documents", {"query": query})


# --- 3. CREWBASE CLASSES ---
@CrewBase
class SQLAgentCrew:
    agents_config = str(_CONFIG_DIR / "agents.yaml")
    tasks_config = str(_CONFIG_DIR / "tasks.yaml")

    # AGENT 1: Schema Analyst (Schema Tools Only)
    @agent
    def schema_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config['schema_analyst'],
            llm=GLOBAL_LLM,
            tools=[mcp_get_database_schema, mcp_search_golden_queries]
        )

    # AGENT 2: SQL Developer (NO TOOLS - Pure Reasoning)
    @agent
    def sql_developer(self) -> Agent:
        return Agent(
            config=self.agents_config['sql_developer'],
            llm=GLOBAL_LLM,
            tools=[]
        )

    # AGENT 3: Database Executor (Execution Tool Only)
    @agent
    def database_executor(self) -> Agent:
        return Agent(
            config=self.agents_config['database_executor'],
            llm=GLOBAL_LLM,
            tools=[mcp_execute_banking_query]
        )

    # TASK 1: Executed by Schema Analyst
    @task
    def fetch_schema_task(self) -> Task:
        return Task(
            config=self.tasks_config['fetch_schema_task'],
            agent=self.schema_analyst()
        )

    # TASK 2: Executed by SQL Developer
    @task
    def draft_sql_task(self) -> Task:
        return Task(
            config=self.tasks_config['draft_sql_task'],
            agent=self.sql_developer(),
            context=[self.fetch_schema_task()]
        )

    # TASK 3: Executed by Database Executor
    @task
    def execute_sql_task(self) -> Task:
        return Task(
            config=self.tasks_config['execute_sql_task'],
            agent=self.database_executor(),
            context=[self.draft_sql_task()]
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=[self.schema_analyst(), self.sql_developer(), self.database_executor()],
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


# --- 4. EXPOSED ASYNC WORKFLOWS ---
async def run_sql_agent(user_question: str):
    result = await SQLAgentCrew().crew().kickoff_async(inputs={"user_question": user_question})
    return result

async def run_rag_agent(user_question: str) -> str:
    result = await RAGAgentCrew().crew().kickoff_async(inputs={"user_question": user_question})
    return str(result)