import os
import json
import asyncio

# 🤖 CrewAI Framework Engine Integration Modules
from crewai import Agent, Task, Crew, LLM

# 🔌 Official Model Context Protocol Client Packages
from mcp import ClientSession
from mcp.client.sse import sse_client

class SQLTranslationService:
    def __init__(self):
        # 🌐 Microservice network endpoints preserved from architectural rules
        self.mcp_server_url = os.getenv("MCP_SERVER_URL")
        
        # 🔌 LiteLLM Connection Point: Point strictly to loopback interface mapping targets
        self.qwen_base_url = (os.getenv("QWEN_APP_URL") or "").rstrip("/")
        
        # 🔑 Security Access Handshake Tokens
        self.api_token = os.getenv("CML_TOKEN") or os.getenv("QWEN_API_KEY") or "litellm-dummy-token"

        # 🧠 Initialize the CrewAI Native LLM Interface pointing directly to your LiteLLM Proxy
        print(f"📡 Connecting CrewAI to Standalone LiteLLM Proxy Gateway at: {self.qwen_base_url}")
        self.llm = LLM(
            model=f"openai/{os.getenv('CML_MODEL_NAME', 'Qwen2.5-3B-Instruct')}",
            base_url=self.qwen_base_url,
            api_key=self.api_token,
            temperature=0.0
        )

    async def _call_mcp_tool(self, tool_name: str, arguments: dict = None) -> str:
        """
        UNIVERSAL NATIVE MCP CLIENT ROUTINE: Connects directly to the universal 
        /sse channel, initializes a session, and routes any arbitrary tool execution 
        request across the protocol stream.
        """
        sse_endpoint = f"{self.mcp_server_url.rstrip('/')}/sse"
        headers = {"Authorization": f"Bearer {self.api_token}"}
        
        try:
            async with sse_client(url=sse_endpoint, headers=headers) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    # Perform official protocol initialization handshake
                    await session.initialize()
                    
                    # Call the tool dynamically using its registered signature payload
                    result = await session.call_tool(tool_name, arguments=arguments or {})
                    
                    if result and result.content:
                        return result.content[0].text
                    return ""
        except Exception as e:
            print(f"⚠️ Native MCP Protocol fetch failed for tool [{tool_name}]: {str(e)}")
            return json.dumps([{"error": f"MCP Gateway Disruption: {str(e)}"}])

    # =========================================================================
    # 📑 PATH A: OPTIMIZED TEXT-TO-SQL ENGINE (DIRECT CONTEXT INJECTION)
    # =========================================================================
    def generate_sql(self, user_question: str) -> str:
        """Deterministic execution pipeline that forces schema adherence for compact models."""
        
        # 1. Fetch unified blueprint (Schema + Centralized Guardrails) over MCP tool stream
        print("📡 Fetching unified database blueprint natively over MCP protocol streams...")
        db_blueprint = asyncio.run(self._call_mcp_tool("get_database_schema"))

        # 2. Define the structural engineering persona
        sql_developer = Agent(
            role="Senior Cloudera Impala Analytics Architect",
            goal="Convert conversational user requests into valid, highly optimized read-only Impala SQL statements.",
            backstory=(
                "You are an expert big data analytics engineer at Bank Jatim specializing in Cloudera SDX environments. "
                "You strictly write queries compatible with the Cloudera Impala engine, using standard ANSI/Hive SQL syntax "
                "and adhering exactly to the provided database blueprint rules."
            ),
            llm=self.llm,
            verbose=True
        )

        # 3. Streamlined Task targeting the centralized blueprint rules
        draft_sql_task = Task(
            description=(
                f"Process the following user query: '{user_question}'.\n\n"
                f"📊 UNIFIED DATABASE BLUEPRINT & SYSTEM OPERATIONAL RULES:\n"
                f"{db_blueprint}\n\n"
                "INSTRUCTION: You must strictly read, respect, and execute your response according "
                "to the metadata layouts, formatting rules, and security boundaries specified in the "
                "UNIFIED DATABASE BLUEPRINT above."
            ),
            expected_output="A clean Cloudera Impala SELECT statement matching the formatting rules and constraints defined in the blueprint context.",
            agent=sql_developer
        )

        # 4. Assemble and launch the automated agent team context
        orchestration_crew = Crew(
            agents=[sql_developer],
            tasks=[draft_sql_task]
        )

        print("⏳ Initiating autonomous CrewAI execution pipeline via LiteLLM application layer...")
        ai_result = str(orchestration_crew.kickoff()).strip()
        return self._extract_sql_from_response(ai_result)

    @staticmethod
    def _extract_sql_from_response(ai_result: str) -> str:
        """Normalize CrewAI output into a plain SQL statement when possible."""
        ai_result = str(ai_result).strip()

        if "```sql" in ai_result:
            return ai_result.split("```sql")[1].split("```")[0].strip()
        if "SELECT" in ai_result.upper():
            return ai_result.replace("```", "").strip()

        return ai_result

    def run_mcp_query(self, sql_query: str) -> list:
        """Synchronous wrapper to execute relational queries via MCP."""
        raw_json = asyncio.run(self._call_mcp_tool("execute_banking_query", {"sql_query": sql_query}))
        try:
            return json.loads(raw_json)
        except Exception:
            # Fallback if the server returned a plain string error message
            return [{"execution_message": raw_json}]

    # =========================================================================
    # 📑 PATH B: KNOWLEDGE BASE VECTOR RETRIEVAL (STANDARDIZED VIA MCP RAG)
    # =========================================================================
    def generate_rag_answer(self, user_question: str) -> str:
        """Coordinates unstructured context parsing with Qwen via LiteLLM to answer policies."""
        print("📡 Fetching semantic document context blocks natively over MCP protocol streams...")
        
        # 🔌 Fetch vector snippets completely through the standardized MCP data layer tool!
        raw_context = asyncio.run(self._call_mcp_tool("search_policy_documents", {"query": user_question}))
        
        try:
            parsed_docs = json.loads(raw_context)
            # Reconstruct the JSON payload arrays into a cleanly structured textual prompt context
            document_context = "\n\n---\n\n".join([
                f"[Source: {d.get('title')}] (Similarity Score: {d.get('score')})\n{d.get('excerpt')}" 
                for d in parsed_docs if "error" not in d
            ])
        except Exception:
            document_context = raw_context
        
        compliance_officer = Agent(
            role="Authoritative Corporate Policy Compliance Specialist",
            goal="Formulate high-fidelity textual responses based exclusively on provided manuals.",
            backstory="You represent the internal policy audit team. You match facts exactly and never speculate.",
            llm=self.llm,
            verbose=True
        )

        evaluate_policy_task = Task(
            description=(
                f"Review the following corporate reference manuals carefully:\n\n"
                f"VERIFIED CONTEXT FROM KNOWLEDGE STORE:\n{document_context}\n\n"
                f"USER QUESTION: {user_question}\n\n"
                f"MANDATE: Rely strictly on the reference text above. If details cannot be derived, "
                f"state clearly that you do not possess that information. Do not hallucinate facts."
            ),
            expected_output="A perfectly formatted conversational text response ready for UI display.",
            agent=compliance_officer
        )

        rag_crew = Crew(
            agents=[compliance_officer],
            tasks=[evaluate_policy_task]
        )

        return str(rag_crew.kickoff()).strip()