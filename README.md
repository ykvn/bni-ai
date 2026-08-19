```
ask-data/                              # Root project directory
│
├── shared/                            # Cross-service shared utilities and configuration
│   ├── __init__.py                    # Package marker for shared utilities
│   ├── config_loader.py               # Global configuration loader that resolves the ask-data/ root, loads .env, and injects env vars (priority: OS > .env)
│   ├── cml_auth.py                    # CML/Cloudera AI authentication helper — builds Bearer token headers for inter-service HTTP calls
│   ├── entry_utils.py                 # Shared service entry-point utilities: bootstraps root, resolves ports, installs deps, launches Uvicorn subprocesses
│   ├── embed_client.py                # Remote embedding & reranking HTTP client — calls the embed-rerank microservice for vector generation and Cross-Encoder reranking
│   ├── model_resolver.py              # CML Model Registry resolver — verifies registered models and downloads HuggingFace weights with NFS fallback
│   ├── qdrant_client.py               # Lightweight Qdrant REST client — handles collection management, bulk document uploads, vector search with CML auth
│   ├── sql_guard.py                   # SQL sanitization & read-only security guard — strips markdown, blocks destructive keywords (INSERT/UPDATE/DROP/etc.)
│   └── __init__.py                    # Package marker
│
├── download_requirements.py           # Pre-downloads all Python dependencies from backend, mcp_server, and qwen_inference requirements.txt into a central .pip_cache
│
├── requirements.txt                   # Monorepo-level dependency manifest with pinned versions for all services
│
├── data/                              # Static data assets: schema definitions, golden queries, value mappings, and policy documents
│   ├── bni_schema_definitions.yaml    # Database schema catalog: tables, columns, types, descriptions, and relationships for BNI's Cloudera Impala warehouse
│   ├── bni_golden_queries.json        # Pre-verified SQL query templates with user intents — used as reference patterns for the SQL agent
│   ├── bni_cube_value_mappings.json   # Maps user-friendly phrasings to database enum/string values (e.g., "aktif" → "ACTIVE")
│   ├── bni_cube_definitions.xlsx        # Master Excel spreadsheet with Tables, Columns, and Value_Mappings sheets (input source for script generation)
│   └── documents/
│       └── Kebijikan-Manajemen-Risiko-Bank-BNI.pdf  # BNI risk management policy document for RAG/knowledge retrieval
│
├── scripts/                           # One-off data transformation and code generation scripts
│   ├── generate_cube_and_mappings.py  # Reads bni_cube_definitions.xlsx and generates bni_cube_definitions.yaml (Cube model) + bni_cube_value_mappings.json
│   └── convert_to_excel.py            # Converts a YAML schema definition into an Excel file with Tables, Columns, and Value_Mappings sheets
│
├── sql/                               # SQL schema and seed data
│   ├── impala_schema.sql              # Impala-specific CREATE TABLE / INSERT statements for 7+ BNI analytical tables with seed data
│   └── schema.sql                     # MySQL/MariaDB-specific schema definitions for the same BNI banking domain (customers, savings, deposits, loans, etc.)
│
├── cube_service/                      # Cube.js semantic layer for BNI's analytical data model
│   ├── docker-compose.yaml            # Docker Compose configuration for running Cube in containerized mode
│   ├── cube_entry.py                  # CML application entry point — bootstraps Node.js PATH, sets Cube env vars, launches npx cubejs-server
│   ├── start_cube.sh                  # Shell script to start Cube semantic layer in CML (alt. entry via bash)
│   └── model/
│       └── cubes/
│           └── bni_cube_definitions.yaml  # Cube semantic model: 7 cubes (customers, savings, deposits, loans, credit_cards, transactions, branch_performance) with measures, dimensions, and joins
│
├── backend/                            # API Gateway REST service (FastAPI)
│   ├── backend_entry.py               # CML application entry — bootstraps shared config, installs deps, launches Uvicorn with backend app on port 8090
│   ├── backend/app/
│   │   ├── __init__.py                # Package marker
│   │   ├── main.py                    # FastAPI app ("Bank ABC NL-to-SQL Core API Gateway") — proxies /ask to CrewAI service, /job/{id} for status, /cancel for cancellation
│   │   ├── core/                      # Core modules (currently empty — holds pycache for ingest workflows)
│   │   ├── schemas/
│   │   │   └── query.py               # Pydantic model: QueryRequest with a single "question" field for incoming user queries
│   │   └── services/                  # Service layer (currently empty)
│   ├── requirements.txt               # Backend-specific dependencies (appears minimal; relies on monorepo requirements.txt)
│   └── test_connection.py             # Standalone script — verifies connectivity between CML cloud container and MySQL database
│
├── litellm_proxy/                      # LiteLLM Proxy Gateway with dynamic CDP authentication
│   ├── proxy_entry.py                 # Entry point — loads .env, registers CDP dynamic auth hook, launches LiteLLM proxy on CML-assigned port (8100)
│   ├── generate_token.py              # CDP JWT token generator — calls "cdp iam generate-workload-auth-token" CLI for BNI's internal CDP instance
│   ├── litellm_config.yaml            # LiteLLM proxy config — maps OpenAI-compatible endpoints to BNI's AI inference URL with Bearer auth
│   └── requirements.txt               # Dependencies (appears minimal; uses litellm from monorepo)
│
├── embed_rerank/                       # Embedding & Reranking microservice (FastAPI)
│   ├── embed_rerank_entry.py          # CML application entry — bootstraps shared config, installs deps, launches Uvicorn on port 8090
│   ├── app/
│   │   └── main.py                    # FastAPI app — loads BGE-M3 embedding model and Cross-Encoder reranker via shared model_resolver, exposes /v1/embeddings and /v1/rerank endpoints
│   └── requirements.txt               # Dependencies (appears minimal)
│
├── qwen_inference/                     # Qwen LLM inference service (two modes)
│   ├── qwen_entry.py                  # GPU entry — downloads Qwen2.5-3B weights, launches vLLM OpenAI-compatible server with AWQ quantization
│   ├── qwen_cpu_entry.py              # CPU entry — bootstraps shared config, launches Uvicorn with app.main:app on port 8001
│   ├── app/
│   │   └── main.py                    # FastAPI app — CPU inference engine using SentenceTransformers/transformers, OpenAI-compatible /v1/chat/completions endpoint
│   ├── download_model.py              # Downloads Qwen2.5-3B-Instruct from HuggingFace Hub to model_weights/ (GPU mode, single-worker)
│   ├── download_cpu_model.py          # Downloads Qwen2.5-3B-Instruct from HuggingFace Hub to model_weights_cpu/ (CPU mode, 2-worker)
│   └── requirements.txt               # Dependencies (appears minimal)
│
├── chromadb_server/                    # ChromaDB HTTP vector store (alternative to Qdrant)
│   ├── chroma_entry.py                # CML application entry — ensures chromadb installed, starts persistent Chroma HTTP server on CML-assigned port
│   ├── chroma_db/                     # Persistent storage directory for ChromaDB
│   └── requirements.txt               # Pinned chromadb + FastAPI + Uvicorn + OpenTelemetry dependencies
│
├── qdrant_server/                      # Qdrant vector store server
│   ├── qdrant_entry.py                # CML application entry — downloads Qdrant binary if needed, generates YAML config, launches Qdrant server with auto-restart monitoring
│   └── qdrant_db/                     # Persistent storage directory for Qdrant vectors
│
├── mcp_server/                         # Model Context Protocol (MCP) Gateway Server
│   ├── mcp_entry.py                   # CML application entry — bootstraps config, runs pre-flight ingestion pipelines (knowledge, schema, golden queries, cube catalog), launches Uvicorn on port 8092
│   ├── test_impala.py                 # Standalone diagnostic script — tests Impala DB connection and configuration loading
│   ├── requirements.txt               # Pinned dependencies: FastAPI, FastMCP, impyla, pypdf, etc.
│   ├── app/
│   │   ├── main.py                    # FastAPI + FastMCP app — registers 4 agentic MCP tools (search_database_schema, search_golden_queries, execute_sql_query, search_policy_documents), SSE transport
│   │   ├── core/
│   │   │   ├── ingest_common.py       # Shared helpers for all ingestion pipelines: bootstrap_env, resolve_data_path, reset_and_index, resolve_reindex_config
│   │   │   ├── ingest_cube_metadata.py  # Ingests Cube catalog (YAML measures/dimensions) and value mappings into Qdrant
│   │   │   ├── ingest_knowledge.py      # Ingests PDF policy documents into Qdrant with page-aware chunking (1500 char chunks, 300 overlap)
│   │   │   ├── ingest_sql_metadata.py  # Ingests schema YAML and golden queries JSON into Qdrant as searchable vectors
│   │   │   ├── reindex_cube_metadata.py  # Reindex entry point for Cube metadata
│   │   │   ├── reindex_knowledge.py      # Reindex entry point for PDF documents
│   │   │   └── reindex_sql_metadata.py   # Reindex entry point for schema + golden queries
│   │   └── tools/
│   │       ├── __init__.py             # Package marker
│   │       ├── config.py               # Pydantic settings — loads env vars for Impala credentials, Qdrant URL, document collection name
│   │       ├── impala_client.py        # Cloudera Impala connection & query execution utility (SSL, PLAIN auth, HTTP transport)
│   │       ├── execute_sql_query.py     # SQL execution tool — sanitizes input, validates read-only, executes via Impala, returns JSON rows
│   │       ├── search_database_schema.py # Schema retrieval tool — smart vector-based schema context (merged from schema_utils)
│   │       ├── search_golden_queries.py  # Golden queries tool — vector search + Cross-Encoder rerank to find verified SQL templates
│   │       ├── rag_search.py             # Policy documents search tool — queries Qdrant for enterprise manuals/SOPs
│   │       ├── schema_utils.py          # Smart schema context retriever — 3-stage pipeline: vector search tables → rerank columns → reconstruct pruned YAML
│   │       ├── chroma_client.py         # ChromaDB client for local vector search (alternative to Qdrant)
│   │       └── qdrant_client.py         # Qdrant client for remote vector search with reranking
│
├── crewai_service/                      # CrewAI Agent Microservice
│   ├── crewai_entry.py                 # CML application entry — bootstraps config, installs deps, launches Uvicorn on port 8091
│   ├── app/
│   │   ├── main.py                     # FastAPI app ("CrewAI Agent Microservice Engine") — job queueing (/process), status (/status/{id}), cancellation (/cancel/{id})
│   │   ├── core/
│   │   │   └── job_db.py               # SQLite job queue — manages job lifecycle (pending → processing → completed/failed/cancelled) with timeout-safe NFS-friendly WAL disabled
│   │   ├── services/
│   │   │   └── agent_engine.py         # Core agent orchestration — defines 4 CrewAI agents (Schema Analyst, SQL Developer, SQL Executor, Compliance Officer), SQL generation flow with retry logic, and RAG agent
│   │   └── worker.py                   # Background async worker loop — polls pending jobs, dispatches to SQL/RAG agents based on the job's `type` (set by the page the question was submitted from), manages concurrency with semaphore
│   ├── config/
│   │   ├── agents.yaml                 # CrewAI agent definitions: schema_analyst, sql_developer, sql_executor, compliance_officer
│   │   └── tasks.yaml                  # CrewAI task templates: fetch_schema_task, draft_sql_task, execute_sql_task, evaluate_policy_task
│   └── requirements.txt                # Dependencies (appears minimal)
│
├── frontend/                            # Gradio Web UI
│   ├── frontend_entry.py               # CML application entry — bootstraps config, installs deps, builds and launches Gradio UI on port 8080
│   ├── app/
│   │   └── main.py                     # Gradio Blocks UI — SQL & RAG tabs (each with question input, job status tracking, SQL/code formatting, DataFrame rendering, cancel button); each tab routes its question to the matching agent via a `type` field
│   ├── package.json                    # Node.js package manifest (empty/minimal — likely not used in CML Python context)
│   ├── requirements.txt                # Frontend dependencies (appears minimal)
│   └── README.md                       # Quick start instructions for running the Gradio app
│
└── system_architecture.mmd              # Mermaid.js diagram defining the system architecture/data flow (at repo root, not in ask-data/)
```
