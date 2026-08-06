import os
import sys
import time
import json
import subprocess
from pathlib import Path

# Suppress SSL certificate verification warnings in enterprise CML environments
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Global config: load the single ask-data/.env BEFORE any service code reads env vars.
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

import shared.config_loader as config_loader
config_loader.bootstrap(hint=_ASK_DATA_ROOT)


def _resolve_frontend_dir() -> Path:
    candidates = []
    if "__file__" in globals():
        current_file = Path(__file__).resolve()
        candidates.extend([current_file.parent, current_file.parent.parent])

    cwd = Path.cwd()
    candidates.extend([
        cwd, cwd / "frontend", cwd / "ask-data" / "frontend",
        cwd / "ask-data", Path("/home/cdsw/ask-data/frontend"),
        Path("/home/cdsw/frontend"), Path("/home/cdsw"),
    ])

    for candidate in candidates:
        candidate_path = candidate.resolve() if hasattr(candidate, "resolve") else Path(candidate)
        if (candidate_path / "frontend_entry.py").exists():
            return candidate_path

    if "__file__" in globals():
        return Path(__file__).resolve().parent
    return cwd


FRONTEND_DIR = _resolve_frontend_dir()
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))


def ensure_dependencies(frontend_dir: Path, env: dict) -> None:
    req_file = frontend_dir / "requirements.txt"
    if not req_file.exists():
        return

    print(f"📦 Validating frontend dependencies from {req_file}...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"],
        check=True, env=env,
    )


def format_response_payload(payload: dict) -> str:
    """
    Formats any query payload (sync or async) into clean Markdown with 
    SQL code blocks and structured Markdown tables.
    """
    if not isinstance(payload, dict):
        return str(payload)

    output_parts = []

    # 1. Natural Language Response / Policy Text
    if payload.get("response"):
        output_parts.append(payload["response"])

    # 2. SQL Query Code Block
    if payload.get("predicted_sql"):
        sql_text = payload["predicted_sql"].strip()
        output_parts.append(f"### 🤖 Generated SQL:\n```sql\n{sql_text}\n```")

    # 3. Data Results Table
    if "data" in payload and payload["data"] is not None:
        data = payload["data"]

        # If data arrived as a stringified JSON string, parse it first
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                pass

        if not data:
            output_parts.append("### 📊 Query Results:\n*Query executed successfully, but returned 0 rows.*")
        elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            row_count = payload.get("row_count", len(data))
            headers_list = list(data[0].keys())

            md_table = f"### 📊 Query Results ({row_count} rows):\n\n"
            md_table += "| " + " | ".join(headers_list) + " |\n"
            md_table += "|" + "|".join(["---"] * len(headers_list)) + "|\n"

            for row in data:
                if isinstance(row, dict):
                    row_values = [str(row.get(h, "")).replace("|", "\\|") for h in headers_list]
                    md_table += "| " + " | ".join(row_values) + " |\n"
                else:
                    clean_val = str(row).replace("|", "\\|")
                    md_table += f"| {clean_val} |\n"

            output_parts.append(md_table)
        else:
            output_parts.append(f"### 📊 Query Results:\n```json\n{json.dumps(data, indent=2, default=str)}\n```")

    if not output_parts:
        return f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"

    return "\n\n".join(output_parts)


def build_ui() -> object:
    import gradio as gr
    import requests

    backend_url = os.environ.get("BACKEND_URL", "").rstrip("/")
    if backend_url.endswith("/process") or backend_url.endswith("/ask"):
        base_api_url = backend_url.rsplit("/", 1)[0]
    else:
        base_api_url = backend_url

    def ask_backend(question: str):
        if not question.strip():
            yield "Please enter a question."
            return

        try:
            cml_token = os.environ.get("CML_TOKEN", "").strip()
            headers = {"Content-Type": "application/json", "accept": "application/json"}
            if cml_token:
                headers["Authorization"] = f"Bearer {cml_token}"

            yield "Submitting question to CrewAI Engine..."
            response = requests.post(
                backend_url, 
                json={"question": question}, 
                headers=headers, 
                timeout=30,
                verify=False
            )
            response.raise_for_status()
            payload = response.json()

            # Handle Asynchronous Job Queue Response
            if "job_id" in payload:
                job_id = payload["job_id"]
                yield f"⏳ Task queued (Job ID: {job_id}). CrewAI is thinking..."
                
                job_status_url = f"{base_api_url}/job/{job_id}"
                
                while True:
                    time.sleep(2.0)
                    
                    status_response = requests.get(
                        job_status_url, 
                        headers=headers, 
                        timeout=10,
                        verify=False
                    )
                    status_response.raise_for_status()
                    job_data = status_response.json()
                    status = job_data.get("status")
                    
                    if status == "completed":
                        final_payload = {}
                        
                        if "result" in job_data and isinstance(job_data["result"], str):
                            try:
                                final_payload = json.loads(job_data["result"])
                            except Exception: 
                                pass
                        elif "result" in job_data and isinstance(job_data["result"], dict):
                            final_payload = job_data["result"]
                        elif "predicted_sql" in job_data or "data" in job_data:
                            final_payload = job_data
                            
                        yield format_response_payload(final_payload)
                        break
                        
                    elif status == "failed":
                        error_msg = job_data.get("error", "Unknown error")
                        yield f"❌ CrewAI Task Failed:\n{error_msg}"
                        break
                    else:
                        yield f"⏳ CrewAI is currently {status} your request..."

            # Handle Direct Synchronous API Response
            else:
                yield format_response_payload(payload)

        except Exception as exc:
            error_details = str(exc) if str(exc) and str(exc) != "0" else repr(exc)
            yield f"❌ Error:\n{error_details}"

    with gr.Blocks(title="Bank Negara Indonesia Q&A") as demo:
        gr.Markdown("# Bank Negara Indonesia Question Assistant")
        question_box = gr.Textbox(label="Question", lines=3)
        submit_btn = gr.Button("Ask")
        output_box = gr.Markdown(label="Answer")

        submit_btn.click(fn=ask_backend, inputs=question_box, outputs=output_box)

    return demo


def main() -> None:
    frontend_dir = _resolve_frontend_dir()
    os.chdir(frontend_dir)
    env = os.environ.copy()
    ensure_dependencies(frontend_dir, env)
    demo = build_ui()
    port = int(os.environ.get("CDSW_APP_PORT", 8080))
    print(f"🌐 Starting Gradio UI on http://127.0.0.1:{port}")
    demo.launch(server_name="127.0.0.1", server_port=port, share=False)


if __name__ == "__main__":
    main()