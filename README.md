```
ask-data/
├── backend/
│   ├── app/
│   │   ├── core/
│   │   │   ├── ingest_knowledge.py       # Core chunking & embedding pipeline
│   │   │   └── reindex_knowledge.py      # Automated ChromaDB re-indexing trigger
│   │   ├── schemas/
│   │   │   └── query.py                  # Pydantic request/response models
│   │   ├── services/
│   │   │   └── translator.py             # Translator orchestrator (CrewAI & MCP caller)
│   │   ├── __init__.py
│   │   ├── database.py                   # Relational DB session handlers
│   │   └── main.py                       # FastAPI application backend entry point
│   ├── chroma_db/                        # Local vector store directory
│   ├── tests/                            # Backend unit and integration tests
│   ├── backend_entry.py                  # CML container startup runner for backend
│   ├── domain_config.yaml                # Master database schema blueprint & rules
│   └── requirements.txt
│
├── data/
│   └── documents/                        # Knowledge base source documents
│       └── KEBIJAKAN KOMUNIKASI DENGAN PEMEGANG SAHAM ATAU INVESTOR.pdf
│
├── data_generation/
│   └── generate_synthetic.py            # Synthetic dataset generation scripts
│
├── frontend/                             # Gradio UI Application layer
│   ├── app/
│   ├── frontend_entry.py                 # CML container entry point for Gradio UI
│   ├── package.json
│   └── requirements.txt
│
├── litellm_proxy/                        # API Gateway & OpenAI Translation Layer
│   ├── litellm_config.yaml               # LiteLLM routing rules (Points to CAINF / Qwen)
│   ├── proxy_entry.py                    # CML container runner for proxy
│   └── requirements.txt
│
├── mcp_server/                           # Decoupled Model Context Protocol Server
│   ├── app/
│   │   ├── tools/                        # 1-to-1 Decoupled Tool Modules
│   │   │   ├── chroma_client.py          # Vector database query handler
│   │   │   ├── config.py                 # Pydantic settings for MCP server
│   │   │   ├── dormant_risk.py           # Account risk matrix calculation logic
│   │   │   ├── execute_banking_query.py  # Dedicated Impala query executor
│   │   │   ├── get_database_schema.py    # Dedicated domain_config.yaml reader
│   │   │   └── impala_client.py          # PyImpala DB connection manager
│   │   └── main.py                       # FastMCP server registration & SSE routes
│   ├── .env                              # Local MCP environment secrets
│   ├── mcp_entry.py                      # CML container startup runner for MCP
│   ├── test_impala.py                    # Standalone Impala connectivity tester
│   └── requirements.txt
│
├── qwen_inference/                       # Local Inference Engine (Optional if using CAINF)
│   ├── app/
│   ├── download_cpu_model.py
│   ├── download_model.py
│   ├── qwen_cpu_entry.py
│   ├── qwen_entry.py
│   └── requirements.txt
│
├── sql/                                  # Database DDLs and initialization scripts
│   ├── impala_schema.sql
│   └── schema.sql
│
├── scripts/
│   └── cml_bootstrap.sh                  # CML workspace bootstrapping setup script
│
├── download_requirements.py              # Offline dependency loader
├── .gitignore
└── README.md

Example of RAG Search: Berdasarkan dokumen kebijakan komunikasi, apa saja prosedur dan kegiatan rutin manajerial yang harus dilakukan oleh Investor Relations terkait dengan pemaparan kinerja kepada analis dan investor?
```