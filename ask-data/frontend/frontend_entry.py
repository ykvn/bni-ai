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


def parse_payload_to_ui(payload: dict):
    """Parses payload into text components and a Pandas DataFrame for UI rendering."""
    import pandas as pd
    import gradio as gr
    
    text_parts = []
    df_update = gr.update(visible=False, value=None)
    
    if not isinstance(payload, dict):
        return str(payload), df_update
        
    # 1. Natural Language Response
    if payload.get("response"):
        text_parts.append(payload["response"])
        
    # 2. SQL Code Block
    if payload.get("predicted_sql"):
        text_parts.append(f"### 🤖 Generated SQL:\n```sql\n{payload['predicted_sql'].strip()}\n```")
        
    # 3. True Tabular DataFrame Parsing
    if "data" in payload and payload["data"] is not None:
        data = payload["data"]
        
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                pass
                
        if isinstance(data, list) and len(data) > 0:
            try:
                df = pd.DataFrame(data)
                df_update = gr.update(visible=True, value=df)
            except Exception as e:
                text_parts.append(f"*(Could not render table: {e})*")
        elif isinstance(data, list) and len(data) == 0:
            text_parts.append("### 📊 Query Results:\n*Query executed successfully, but returned 0 rows.*")
            
    # Fallback if entirely unrecognized
    if not text_parts and df_update["visible"] is False:
        text_parts.append(f"```json\n{json.dumps(payload, indent=2, default=str)}\n```")
        
    return "\n\n".join(text_parts), df_update


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
            yield "Please enter a question.", gr.update(visible=False)
            return

        try:
            cml_token = os.environ.get("CML_TOKEN", "").strip()
            headers = {"Content-Type": "application/json", "accept": "application/json"}
            if cml_token:
                headers["Authorization"] = f"Bearer {cml_token}"

            yield "Submitting question to CrewAI Engine...", gr.update(visible=False)
            
            response = requests.post(
                backend_url, 
                json={"question": question}, 
                headers=headers, 
                timeout=30,
                verify=False
            )
            response.raise_for_status()
            payload = response.json()

            if "job_id" in payload:
                job_id = payload["job_id"]
                yield f"⏳ Task queued (Job ID: {job_id}). CrewAI is thinking...", gr.update(visible=False)
                
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
                        
                        # -------------------------------------------------------------
                        # 🚀 NEW: Robust Payload Unwrapping
                        # -------------------------------------------------------------
                        final_payload = job_data
                        
                        if "result" in job_data:
                            if isinstance(job_data["result"], str):
                                try:
                                    final_payload = json.loads(job_data["result"])
                                except Exception:
                                    final_payload = {"response": job_data["result"]}
                            elif isinstance(job_data["result"], dict):
                                final_payload = job_data["result"]
                                
                        # Matches the exact structure shown in your screenshot
                        elif "data" in job_data and isinstance(job_data["data"], dict):
                            if "predicted_sql" in job_data["data"]:
                                final_payload = job_data["data"]
                        # -------------------------------------------------------------

                        text_out, df_out = parse_payload_to_ui(final_payload)
                        yield text_out, df_out
                        break
                        
                    elif status == "failed":
                        error_msg = job_data.get("error", "Unknown error")
                        yield f"❌ CrewAI Task Failed:\n{error_msg}", gr.update(visible=False)
                        break
                    else:
                        yield f"⏳ CrewAI is currently {status} your request...", gr.update(visible=False)
            else:
                text_out, df_out = parse_payload_to_ui(payload)
                yield text_out, df_out
                
        except Exception as exc:
            error_details = str(exc) if str(exc) and str(exc) != "0" else repr(exc)
            yield f"❌ Error:\n{error_details}", gr.update(visible=False)

    with gr.Blocks(title="Bank Negara Indonesia Q&A") as demo:
        gr.Markdown("# Bank Negara Indonesia Question Assistant")
        question_box = gr.Textbox(label="Question", lines=3)
        submit_btn = gr.Button("Ask")
        
        output_text = gr.Markdown(label="Answer & SQL")
        output_table = gr.Dataframe(label="Query Results", visible=False, interactive=False)

        submit_btn.click(
            fn=ask_backend, 
            inputs=question_box, 
            outputs=[output_text, output_table]
        )

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