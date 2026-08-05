import os
import sys
import time
import json
import subprocess
from pathlib import Path

# Global config: load the single ask-data/.env BEFORE any service code reads env vars.
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

import shared.config_loader as config_loader
config_loader.bootstrap(hint=_ASK_DATA_ROOT)


def _resolve_frontend_dir() -> Path:
    """Resolve the frontend directory for CML and local execution."""
    candidates = []

    if "__file__" in globals():
        current_file = Path(__file__).resolve()
        candidates.extend([
            current_file.parent,
            current_file.parent.parent,
        ])

    cwd = Path.cwd()
    candidates.extend([
        cwd,
        cwd / "frontend",
        cwd / "ask-data" / "frontend",
        cwd / "ask-data",
        Path("/home/cdsw/ask-data/frontend"),
        Path("/home/cdsw/frontend"),
        Path("/home/cdsw"),
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
    """Install frontend dependencies if requirements.txt exists."""
    req_file = frontend_dir / "requirements.txt"
    if not req_file.exists():
        print(f"⚠️ No requirements.txt found at {req_file}. Skipping dependency installation.")
        return

    print(f"📦 Validating frontend dependencies from {req_file}...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"],
            check=True,
            env=env,
        )
        print("✅ Frontend dependencies verified successfully.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Critical Error: Failed to configure frontend dependencies: {str(e)}")
        sys.exit(1)


def build_ui() -> object:
    import gradio as gr
    import requests

    backend_url = os.environ.get("BACKEND_URL", "").rstrip("/")
    
    # Intelligently extract the base URL for polling endpoints
    if backend_url.endswith("/process") or backend_url.endswith("/ask"):
        base_api_url = backend_url.rsplit("/", 1)[0]
    else:
        base_api_url = backend_url

    def ask_backend(question: str):
        if not question.strip():
            yield "Please enter a question."
            return

        try:
            # 🔑 Read CML_TOKEN from environment and prepare headers
            cml_token = os.environ.get("CML_TOKEN", "").strip()
            headers = {
                "Content-Type": "application/json",
                "accept": "application/json",
            }
            if cml_token:
                headers["Authorization"] = f"Bearer {cml_token}"

            # 1. Submit the initial job
            yield "Submitting question to CrewAI Engine..."
            response = requests.post(
                backend_url,
                json={"question": question},
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            payload = response.json()

            # Check if this is an async job response
            if "job_id" in payload:
                job_id = payload["job_id"]
                yield f"⏳ Task queued (Job ID: {job_id}). CrewAI is thinking..."
                
                # 2. Polling Loop
                job_status_url = f"{base_api_url}/job/{job_id}"
                
                while True:
                    time.sleep(2.0) # Wait 2 seconds between checks
                    
                    status_response = requests.get(job_status_url, headers=headers, timeout=10)
                    status_response.raise_for_status()
                    job_data = status_response.json()
                    
                    status = job_data.get("status")
                    
                    if status == "completed":
                        result_str = job_data.get("result", "{}")
                        try:
                            # Parse the JSON string payload stored in the database
                            final_payload = json.loads(result_str)
                            
                            # Format output cleanly
                            if final_payload.get("response"):
                                yield final_payload["response"]
                            elif final_payload.get("data"):
                                yield json.dumps(final_payload["data"], indent=2)
                            else:
                                yield "✅ Task completed, but no data was returned."
                        except Exception as parse_exc:
                            yield f"✅ Task completed. Raw Result:\n{result_str}"
                        break
                        
                    elif status == "failed":
                        error_msg = job_data.get("error", "Unknown error")
                        yield f"❌ CrewAI Task Failed:\n{error_msg}"
                        break
                        
                    else:
                        # Job is still pending or processing
                        yield f"⏳ CrewAI is currently {status} your request..."

            else:
                # Fallback for older synchronous backend endpoints
                if payload.get("response"):
                    yield payload["response"]
                elif payload.get("data"):
                    yield json.dumps(payload["data"], indent=2)
                else:
                    yield str(payload)
                    
        except requests.exceptions.RequestException as exc:
            yield f"❌ Network Error contacting backend:\n{exc}"
        except Exception as exc:
            yield f"❌ Unexpected Error:\n{exc}"

    with gr.Blocks(title="Bank Negara Indonesia Q&A") as demo:
        gr.Markdown("# Bank Negara Indonesia Question Assistant")
        gr.Markdown("Ask a question and it will be sent to the backend API.")

        question_box = gr.Textbox(label="Question", lines=3)
        submit_btn = gr.Button("Ask")
        output_box = gr.Textbox(label="Answer", lines=10)

        # Connect the generator function
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