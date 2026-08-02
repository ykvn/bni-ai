```
ask-data/
├── backend/
│   ├── app/
│   │   ├── core/
│   │   │   ├── ingest_knowledge.py       # Core chunking & embedding pipeline
│   │   │   └── reindex_knowledge.py      # Automated ChromaDB re-indexing trigger
│   │   ├── schemas/                      # Pydantic request/response models
│   │   ├── services/
│   │   │   ├── .gitkeep
│   │   │   └── translator.py             # Translator orchestrator (CrewAI & MCP caller)
│   │   ├── __init__.py
│   │   └── main.py                       # FastAPI application backend entry point
│   ├── tests/                            # Backend unit and integration tests
│   ├── backend_entry.py                  # CML container startup runner for backend
│   ├── domain_config.yaml                # Master database schema blueprint & rules
│   └── requirements.txt
│
├── chroma_server/                        # Dedicated Standalone ChromaDB Service
│   ├── chroma_db/                        # Persistent vector store directory
│   └── chroma_entry.py                   # CML entry point for Chroma HTTP service
│
├── data/
│   └── documents/                        # Knowledge base source PDF documents
│
├── frontend/                             # Gradio UI Application layer
│   ├── app/
│   │   └── .gitkeep
│   ├── frontend_entry.py                 # CML container entry point for Gradio UI
│   ├── package.json
│   └── requirements.txt
│
├── litellm_proxy/                        # API Gateway & OpenAI Translation Layer
│   ├── litellm_config.yaml               # LiteLLM routing rules (Points to Qwen)
│   ├── proxy_entry.py                    # CML container runner for proxy
│   └── requirements.txt
│
├── mcp_server/                           # Model Context Protocol Microservice
│   ├── app/
│   │   ├── tools/                        # Decoupled MCP Tool Modules
│   │   │   ├── __init__.py
│   │   │   ├── chroma_client.py          # Direct REST vector query client
│   │   │   ├── config.py                 # Pydantic settings for MCP server
│   │   │   ├── execute_banking_query.py  # Dedicated Impala query executor
│   │   │   ├── impala_client.py          # PyImpala DB connection manager
│   │   │   └── rag_search.py             # 🆕 Tool for semantic PDF context retrieval
│   │   └── main.py                       # FastMCP server registration & SSE routes
│   ├── mcp_entry.py                      # CML container startup runner for MCP
│   ├── test_impala.py                    # Standalone Impala connectivity tester
│   └── requirements.txt
│
├── qwen_inference/                       # CPU Inference Engine
│   ├── app/
│   │   └── main.py                       # FastAPI server for CPU model endpoint
│   ├── download_cpu_model.py
│   ├── download_model.py
│   ├── qwen_cpu_entry.py
│   ├── qwen_entry.py
│   └── requirements.txt
│
├── shared/                               # Shared Utilities Across Microservices
│   ├── __init__.py
│   └── config_loader.py                  # Global .env bootstrap loader
│
├── sql/                                  # Database DDLs and initialization scripts
│   ├── impala_schema.sql
│
├── scripts/
│   └── cml_bootstrap.sh                  # CML workspace bootstrapping setup script
│
├── .env                                  # Global environment file for all services
├── .env.example                          # Template for environment configuration
├── download_requirements.py              # Offline dependency loader
├── .gitignore
└── README.md

Example of RAG Search: Berdasarkan dokumen kebijakan komunikasi, apa saja prosedur dan kegiatan rutin manajerial yang harus dilakukan oleh Investor Relations terkait dengan pemaparan kinerja kepada analis dan investor?
```