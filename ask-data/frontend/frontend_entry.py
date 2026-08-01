import os
import sys
import subprocess
from pathlib import Path

# 🎯 Global config: load the single ask-data/.env BEFORE any service code reads env vars.
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

    backend_url = os.environ.get("BACKEND_URL", "http://127.0.0.1:8090/ask")

    def ask_backend(question: str):
        if not question.strip():
            return "Please enter a question."

        try:
            # 🔑 Read CML_TOKEN from environment and prepare headers
            cml_token = os.environ.get("CML_TOKEN", "").strip()
            headers = {
                "Content-Type": "application/json",
                "accept": "application/json",
            }
            if cml_token:
                headers["Authorization"] = f"Bearer {cml_token}"

            response = requests.post(
                backend_url,
                json={"question": question},
                headers=headers,
                timeout=120,
            )
            response.raise_for_status()
            payload = response.json()

            if payload.get("response"):
                return payload["response"]
            if payload.get("data"):
                return payload["data"]
            return str(payload)
        except Exception as exc:
            return f"Error contacting backend: {exc}"

    with gr.Blocks(title="Bank ABC Q&A") as demo:
        gr.Markdown("# Bank ABC Question Assistant")
        gr.Markdown("Ask a question and it will be sent to the backend API.")

        question_box = gr.Textbox(label="Question", lines=3)
        submit_btn = gr.Button("Ask")
        output_box = gr.Textbox(label="Answer", lines=10)

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