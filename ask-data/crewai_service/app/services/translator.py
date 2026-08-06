import os
import json
import httpx
import yaml
from pathlib import Path

# CrewAI Framework Engine Integration Modules
from crewai import Agent, Task, Crew, LLM
from crewai.tools import tool  # wrap MCP endpoints into CrewAI tools

# Official Model Context Protocol Client Packages
from mcp import ClientSession
from mcp.client.sse import sse_client

_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def _make_insecure_httpx_client(**kwargs) -> httpx.AsyncClient:
    kwargs["verify"] = False
    kwargs["follow_redirects"] = True
    return httpx.AsyncClient(**kwargs)


class SQLTranslationService:
    def __init__(self):
        self.mcp_server_url = os.getenv("MCP_SERVER_URL", "").rstrip("/")
        
        self.litellm_proxy_url = (
            os.getenv("LITELLM_PROXY_URL") 
            or os.getenv("LITELLM_APP_URL") 
            or ""
        ).rstrip("/")
        
        # Strictly uses CML_TOKEN for internal platform authentication
        self.api_token = (
            os.getenv("CML_TOKEN") 
            or os.getenv("LITELLM_API_KEY") 
            or ""
        ).strip()

        target_model = os.getenv("CML_MODEL_NAME", "")

        self.llm = LLM(
            model=f"openai/{target_model}",
            base_url=self.litellm_proxy_url,
            api_key=self.api_token,
            temperature=0.0,
            top_p=1.0,
            enable_thinking=False,
            timeout=300,
            request_timeout=300
        )

        agents_yaml_path = _CONFIG_DIR / "agents.yaml"
        tasks_yaml_path = _CONFIG_DIR / "tasks.yaml"

        with open(agents_yaml_path, "r", encoding="utf-8") as f:
            self.agents_config = yaml.safe_load(f)

        with open(tasks_yaml_path, "r", encoding="utf-8") as f:
            self.tasks_config = yaml.safe_load(f)

    async def _call_mcp_tool(self, tool_name: str, arguments: dict = None) -> str:
        sse_endpoint = f"{self.mcp_server_url}/sse"
        
        headers = {}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
            headers["X-CDSW-API-Key"] = self.api_token
        
        try:
            async with sse_client(
                url=sse_endpoint, 
                headers=headers,
                sse_read_timeout=60.0,
                httpx_client_factory=_make_insecure_httpx_client
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments=arguments or {})
                    if result and result.content:
                        return result.content[0].text
                    return ""
        except Exception as e:
            print(f"⚠️ Native MCP Protocol fetch failed for tool [{tool_name}]: {str(e)}")
            return json.dumps([{"error": f"MCP Gateway Disruption: {str(e)}"}])

    # =========================================================================
    # 📑 PATH A: OPTIMIZED TEXT-TO-SQL ENGINE (DYNAMIC RAG INJECTION)
    # =========================================================================
    async def generate_sql(self, user_question: str) -> str:
        """Deterministic execution pipeline that forces schema adherence."""
        print("Forcing semantic retrieval via MCP embed & rerank modules...")
        
        # 1. GUARANTEE execution by running the tools in Python first
        golden_context = await self._call_mcp_tool("search_golden_queries", {"user_question": user_question})
        schema_context = await self._call_mcp_tool("get_database_schema", {"user_question": user_question})

        # 2. Only give the agent the execution tool
        @tool("execute_banking_query")
        async def mcp_execute_banking_query(query: str) -> str:
            """Executes a SQL query against the database."""
            return await self._call_mcp_tool("execute_banking_query", {"sql_query": query})

        sql_developer = Agent(
            config=self.agents_config["sql_developer"],
            llm=self.llm,
            tools=[mcp_execute_banking_query],
            verbose=True
        )

        draft_sql_task = Task(
            config=self.tasks_config["draft_sql_task"],
            agent=sql_developer
        )

        orchestration_crew = Crew(
            agents=[sql_developer],
            tasks=[draft_sql_task],
            verbose=True
        )

        print("⏳ Initiating autonomous CrewAI execution pipeline via LiteLLM application layer...")
        # 3. Inject the retrieved context directly into the prompt
        ai_result = await orchestration_crew.kickoff_async(inputs={
            "user_question": user_question,
            "golden_context": golden_context,
            "schema_context": schema_context
        })
        
        return self._extract_sql_from_response(str(ai_result))

    @staticmethod
    def _extract_sql_from_response(ai_result: str) -> str:
        ai_result = str(ai_result).strip()

        if "```sql" in ai_result:
            return ai_result.split("```sql")[1].split("```")[0].strip()
        if "SELECT" in ai_result.upper():
            return ai_result.replace("```", "").strip()

        return ai_result

    async def run_mcp_query(self, sql_query: str) -> list:
        raw_json = await self._call_mcp_tool("execute_banking_query", {"sql_query": sql_query})
        try:
            return json.loads(raw_json)
        except Exception:
            return [{"execution_message": raw_json}]

    # =========================================================================
    # 📑 PATH B: KNOWLEDGE BASE VECTOR RETRIEVAL (STANDARDIZED VIA MCP RAG)
    # =========================================================================
    async def generate_rag_answer(self, user_question: str) -> str:
        print("📡 Fetching semantic document context blocks natively over MCP protocol streams...")
        raw_context = await self._call_mcp_tool("search_policy_documents", {"query": user_question})
        
        try:
            parsed_docs = json.loads(raw_context)
            document_context = "\n\n---\n\n".join([
                f"[Source: {d.get('title')}] (Similarity Score: {d.get('score')})\n{d.get('excerpt')}" 
                for d in parsed_docs if "error" not in d
            ])
        except Exception:
            document_context = raw_context
        
        compliance_officer = Agent(
            config=self.agents_config["compliance_officer"],
            llm=self.llm,
            verbose=True
        )

        evaluate_policy_task = Task(
            config=self.tasks_config["evaluate_policy_task"],
            agent=compliance_officer
        )

        rag_crew = Crew(
            agents=[compliance_officer],
            tasks=[evaluate_policy_task],
            verbose=True
        )

        ai_result = await rag_crew.kickoff_async(inputs={
            "user_question": user_question,
            "document_context": document_context
        })

        return str(ai_result).strip()