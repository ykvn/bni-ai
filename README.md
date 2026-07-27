```
ask-data/
├── backend/                             # Core Backend Microservice (FastAPI & CrewAI Agents)
│   ├── app/                             # Main application package directory
│   │   ├── core/                        # Data processing & ingestion pipelines
│   │   │   ├── ingest_knowledge.py      # Automated PDF extraction & ChromaDB vector ingestion
│   │   │   └── reindex_knowledge.py     # Vector store index rebuilding utility
│   │   ├── schemas/                     # Pydantic data schemas & response payload models
│   │   ├── services/                    # Agentic orchestration & LLM routing
│   │   │   └── translator.py            # CrewAI agent definitions (SQL Generator & RAG Compliance)
│   │   ├── database.py                  # Database connection routines and ORM session managers
│   │   └── main.py                      # Primary FastAPI app routing /ask REST endpoints
│   ├── chroma_db/                       # Persistent disk storage for ChromaDB vector embeddings
│   ├── tests/                           # Unit and integration test suites for backend APIs
│   ├── backend_entry.py                 # Production launcher for running the Backend CML app
│   ├── domain_config.yaml               # Agent persona prompts & domain metadata configurations
│   ├── requirements.txt                 # Backend Python package dependencies
│   └── test_connection.py               # Diagnostic script for checking backend connectivity
│
├── data/                                # Document knowledge store for RAG
│   └── documents/                       # Enterprise policy PDF manuals (e.g., Bank Jatim Investor SOP)
│
├── data_generation/                     # Synthetic test data generation tools
│
├── frontend/                            # User Interface Application (Gradio Web UI)
│   ├── app/                             # UI layouts, chat components, and event handlers
│   ├── package.json                     # Frontend metadata configuration
│   ├── README.md                        # Frontend-specific setup and configuration guide
│   └── requirements.txt                 # Python dependencies for Gradio UI runtime
│
├── litellm_proxy/                       # LiteLLM Proxy Gateway Service
│   ├── litellm_config.yaml              # Proxy route mappings, API keys, and model fallback configs
│   └── requirements.txt                 # Dependencies for running LiteLLM proxy
│
├── mcp_server/                          # Model Context Protocol (MCP) Server Infrastructure
│   ├── app/                             # MCP tool registration package
│   │   ├── tools/                       # Modular execution tools connected over SSE
│   │   │   ├── chroma_client.py         # ChromaDB query client & vector similarity search logic
│   │   │   ├── config.py                # Centralized Pydantic application settings & .env parser
│   │   │   ├── dormant_risk.py          # Compliance tool for calculating dormant account risk scores
│   │   │   ├── impala_client.py         # Database connection wrapper for Cloudera Impala
│   │   │   ├── rag_search.py            # Vector retrieval tool execution handler
│   │   │   └── sql_query.py             # Read-only SQL query execution engine
│   │   └── main.py                      # FastMCP app routing tools over Server-Sent Events (SSE)
│   ├── .env                             # Environment variables (Impala credentials, Chroma paths)
│   ├── mcp_entry.py                     # Production launcher script for running the MCP server
│   ├── requirements.txt                 # Dependencies for MCP protocol execution
│   └── test_impala.py                   # Standalone diagnostic connection test for Impala DB
│
├── qwen_inference/                      # Local LLM Inference Engine Service
│   ├── app/                             # Local inference endpoint wrapper
│   │   └── main.py                      # OpenAI-compatible API server exposing local LLM
│   ├── download_cpu_model.py            # Utility script to pre-fetch CPU-quantized LLM weights
│   ├── download_model.py                # Hugging Face model downloader for Qwen model weights
│   ├── qwen_cpu_entry.py                # CPU inference runtime launcher
│   ├── qwen_entry.py                    # Primary GPU inference server entry point
│   └── requirements.txt                 # Dependencies for local transformer model loading
│
├── sql/                                 # SQL Schema Definitions & DDL Scripts
│   ├── impala_schema.sql                # Table DDL, column types, and schemas for Cloudera Impala
│   └── schema.sql                       # Relational database schema references
│
├── download_requirements.py             # Utility to pre-download Python wheels for offline setups
├── scripts/                             # Environment orchestration scripts
│   └── cml_bootstrap.sh                 # Environment setup shell script for Cloudera AI (CML)
├── .gitignore                           # Git version control exclusion patterns
└── README.md                            # Main system documentation & architecture overview

Example of RAG Search: Berdasarkan dokumen kebijakan komunikasi, apa saja prosedur dan kegiatan rutin manajerial yang harus dilakukan oleh Investor Relations terkait dengan pemaparan kinerja kepada analis dan investor?
```