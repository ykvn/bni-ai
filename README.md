```
├── ask-data
│   ├── backend
│   │   ├── app
│   │   │   ├── __init__.py
│   │   │   ├── core
│   │   │   ├── main.py
│   │   │   ├── schemas
│   │   │   │   └── query.py
│   │   │   └── services
│   │   ├── backend_entry.py
│   │   ├── requirements.txt
│   │   └── test_connection.py
│   ├── chroma_server
│   │   ├── chroma_db
│   │   ├── chroma_entry.py
│   │   └── requirements.txt
│   ├── crewai_service
│   │   ├── app
│   │   │   ├── core
│   │   │   │   └── job_db.py
│   │   │   ├── main.py
│   │   │   ├── services
│   │   │   │   └── translator.py
│   │   │   └── worker.py
│   │   ├── config
│   │   │   ├── agents.yaml
│   │   │   └── tasks.yaml
│   │   └── crewai_entry.py
│   ├── cube_service
│   │   ├── docker-compose.yaml
│   │   └── model
│   │       └── cubes
│   │           └── bni_cube_definitions.yaml
│   ├── data
│   │   ├── bni_cube_definitions.xlsx
│   │   ├── bni_cube_value_mappings.json
│   │   ├── bni_golden_queries.json
│   │   ├── bni_schema_definitions.yaml
│   │   └── documents
│   │       └── Kebijakan-Manajemen-Risiko-Bank-BNI.pdf
│   ├── data_generation
│   │   └── generate_synthetic.py
│   ├── download_requirements.py
│   ├── embed_rerank
│   │   ├── app
│   │   │   └── main.py
│   │   └── embed_rerank_entry.py
│   ├── frontend
│   │   ├── app
│   │   │   └── main.py
│   │   ├── frontend_entry.py
│   │   ├── package.json
│   │   ├── README.md
│   │   └── requirements.txt
│   ├── litellm_proxy
│   │   ├── generate_token.py
│   │   ├── litellm_config.yaml
│   │   ├── proxy_entry.py
│   │   └── requirements.txt
│   ├── mcp_server
│   │   ├── app
│   │   │   ├── core
│   │   │   │   ├── ingest_common.py
│   │   │   │   ├── ingest_cube_metadata.py
│   │   │   │   ├── ingest_knowledge.py
│   │   │   │   ├── ingest_sql_metadata.py
│   │   │   │   ├── reindex_cube_metadata.py
│   │   │   │   ├── reindex_knowledge.py
│   │   │   │   └── reindex_sql_metadata.py
│   │   │   ├── main.py
│   │   │   └── tools
│   │   │       ├── __init__.py
│   │   │       ├── chroma_client.py
│   │   │       ├── config.py
│   │   │       ├── execute_banking_query.py
│   │   │       ├── get_database_schema.py
│   │   │       ├── impala_client.py
│   │   │       ├── qdrant_client.py
│   │   │       ├── rag_search.py
│   │   │       ├── schema_utils.py
│   │   │       └── search_golden_queries.py
│   │   ├── mcp_entry.py
│   │   ├── requirements.txt
│   │   └── test_impala.py
│   ├── qdrant_server
│   │   ├── qdrant_db
│   │   └── qdrant_entry.py
│   ├── qwen_inference
│   │   ├── app
│   │   │   └── main.py
│   │   ├── download_cpu_model.py
│   │   ├── download_model.py
│   │   ├── qwen_cpu_entry.py
│   │   ├── qwen_entry.py
│   │   └── requirements.txt
│   ├── requirements.txt
│   ├── scripts
│   │   ├── convert_to_excel.py
│   │   └── generate_cube_and_mappings.py
│   ├── shared
│   │   ├── __init__.py
│   │   ├── __init__.pyc
│   │   ├── cml_auth.py
│   │   ├── config_loader.py
│   │   ├── embed_client.py
│   │   ├── entry_utils.py
│   │   ├── model_resolver.py
│   │   ├── qdrant_client.py
│   │   └── sql_guard.py
│   └── sql
│       ├── impala_schema.sql
│       └── schema.sql
├── README.md
└── system_architecture.mmd
```
