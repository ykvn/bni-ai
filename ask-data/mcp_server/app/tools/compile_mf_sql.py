import os
import json
import httpx
from shared.cml_auth import build_cml_headers

async def compile_mf_sql(json_payload: str | dict) -> str:
    """
    Sends a JSON query payload to the dbt MetricFlow API to generate SQL.
    Returns the raw Impala SQL string. Does NOT execute it.
    """
    try:
        # Parse JSON safely
        if isinstance(json_payload, str):
            payload_dict = json.loads(json_payload)
        else:
            payload_dict = json_payload
            
        print(f"📦 [compile_mf_sql] Sending Payload to dbt: {json.dumps(payload_dict)}", flush=True)

        base_url = os.getenv("DBT_METRICFLOW_URL", "http://127.0.0.1:8092").rstrip("/")
        endpoint = f"{base_url}/api/v1/load"

        cml_token = os.getenv("CML_TOKEN") or os.getenv("CDP_TOKEN")
        headers = build_cml_headers(cml_token) if cml_token else {}

        async with httpx.AsyncClient(verify=False) as client:
            response = await client.post(
                endpoint,
                json=payload_dict,
                headers=headers,
                timeout=30.0
            )
            
            if response.status_code != 200:
                print(f"❌ [compile_mf_sql] dbt API Error ({response.status_code}): {response.text}", flush=True)
                return f"MetricFlow API Error ({response.status_code}): {response.text}"
                
            result_data = response.json()

            # RETURN THE SQL STRING INSTEAD OF EXECUTING IT
            sql_to_run = result_data.get("sql")
            if sql_to_run:
                return sql_to_run
            return json.dumps(result_data)

    except Exception as e:
        print(f"❌ [compile_mf_sql] Tool Exception: {str(e)}", flush=True)
        return f"MetricFlow Compilation Error: {str(e)}"