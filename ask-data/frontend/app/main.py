import os
import time
import json
import requests
from datetime import datetime
import pandas as pd
import gradio as gr

from shared.cml_auth import build_cml_headers


def parse_payload_to_ui(payload: dict):
    """Parses payload into text components and a Pandas DataFrame for UI rendering."""
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
    """Constructs and returns the Gradio Blocks UI instance."""
    backend_url = os.environ.get("BACKEND_URL", "").rstrip("/")
    if backend_url.endswith("/process") or backend_url.endswith("/ask"):
        base_api_url = backend_url.rsplit("/", 1)[0]
    else:
        base_api_url = backend_url

    def format_job_info(job_id: str, status: str, start_time: float, is_final: bool = False):
        """Helper to render standardized Markdown Status Box vertically."""
        elapsed = int(time.time() - start_time)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        status_upper = status.upper()
        if status_upper in ("COMPLETED", "SUCCESS"):
            badge = "✅ SUCCESS"
        elif status_upper == "FAILED":
            badge = "❌ FAILED"
        else:
            badge = f"⏳ {status_upper}"

        time_label = "Completed Time" if is_final else "Current Time"

        # Formatted vertically using Markdown bullets
        return (
            f"### Job Execution Information\n"
            f"- **Job ID:** `{job_id}`\n"
            f"- **Status:** {badge}\n"
            f"- **{time_label}:** `{now_str}` (Duration: `{elapsed}s`)\n"
        )

    def ask_backend(question: str):
        if not question.strip():
            yield (
                gr.update(visible=False, value=""),
                "Please enter a valid question.",
                gr.update(visible=False),
                gr.update(interactive=True)  # Re-enable button
            )
            return

        start_time = time.time()
        
        # Initial yield before network dispatch (Disable button immediately)
        initial_job_box = (
            f"### Job Execution Information\n"
            f"- **Job ID:** `Submitting...`\n"
            f"- **Status:** ⏳ ENQUEUEING\n"
            f"- **Current Time:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
        )
        yield (
            gr.update(visible=True, value=initial_job_box), 
            "Submitting question to CrewAI Engine...", 
            gr.update(visible=False),
            gr.update(interactive=False) # Disable button while processing
        )

        try:
            headers = build_cml_headers(extra={"Content-Type": "application/json", "accept": "application/json"})

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
                job_status_url = f"{base_api_url}/job/{job_id}"
                
                while True:
                    time.sleep(1.0)
                    
                    status_response = requests.get(
                        job_status_url, 
                        headers=headers, 
                        timeout=10,
                        verify=False
                    )
                    status_response.raise_for_status()
                    job_data = status_response.json()
                    status = job_data.get("status", "processing")

                    if status == "completed":
                        final_payload = job_data
                        
                        if "result" in job_data:
                            if isinstance(job_data["result"], str):
                                try:
                                    final_payload = json.loads(job_data["result"])
                                except Exception:
                                    final_payload = {"response": job_data["result"]}
                            elif isinstance(job_data["result"], dict):
                                final_payload = job_data["result"]
                                
                        elif "data" in job_data and isinstance(job_data["data"], dict):
                            if "predicted_sql" in job_data["data"]:
                                final_payload = job_data["data"]

                        text_out, df_out = parse_payload_to_ui(final_payload)
                        
                        job_box_completed = format_job_info(job_id, "SUCCESS", start_time, is_final=True)
                        yield (
                            gr.update(visible=True, value=job_box_completed), 
                            text_out, 
                            df_out,
                            gr.update(interactive=True) # Re-enable button on success
                        )
                        break
                        
                    elif status == "failed":
                        error_msg = job_data.get("error", "Unknown error encountered.")
                        job_box_failed = format_job_info(job_id, "FAILED", start_time, is_final=True)
                        yield (
                            gr.update(visible=True, value=job_box_failed), 
                            f"❌ Task Failed:\n{error_msg}", 
                            gr.update(visible=False),
                            gr.update(interactive=True) # Re-enable button on failure
                        )
                        break
                        
                    else:
                        job_box_running = format_job_info(job_id, status, start_time, is_final=False)
                        yield (
                            gr.update(visible=True, value=job_box_running), 
                            "⏳ CrewAI is currently executing your request...", 
                            gr.update(visible=False),
                            gr.update(interactive=False) # Keep button disabled while polling
                        )
            else:
                text_out, df_out = parse_payload_to_ui(payload)
                job_box_direct = format_job_info("N/A (Direct)", "SUCCESS", start_time, is_final=True)
                yield (
                    gr.update(visible=True, value=job_box_direct), 
                    text_out, 
                    df_out,
                    gr.update(interactive=True) # Re-enable button on direct return
                )
                
        except Exception as exc:
            error_details = str(exc) if str(exc) and str(exc) != "0" else repr(exc)
            job_box_err = format_job_info("ERROR", "FAILED", start_time, is_final=True)
            yield (
                gr.update(visible=True, value=job_box_err), 
                f"❌ Exception Error:\n{error_details}", 
                gr.update(visible=False),
                gr.update(interactive=True) # Re-enable button on exception
            )

    with gr.Blocks(title="Bank Negara Indonesia Q&A") as demo:
        gr.Markdown("# Bank Negara Indonesia Zero Query Assistant")
        
        question_box = gr.Textbox(label="Question", lines=3)
        submit_btn = gr.Button("Ask")

        # Separate Information Box for JOB ID & Running Status
        job_info_box = gr.Markdown(visible=False)

        output_text = gr.Markdown(label="Answer & SQL")
        output_table = gr.Dataframe(label="Query Results", visible=False, interactive=False)

        submit_btn.click(
            fn=ask_backend, 
            inputs=question_box, 
            # Added submit_btn to outputs to control its interactive state
            outputs=[job_info_box, output_text, output_table, submit_btn],
            concurrency_limit=None,  # 🚀 Fixes the queuing issue (Allows parallel tab execution)
            show_progress="hidden"   # 🚀 Fixes the UI layout (Hides Gradio's floating orange boxes)
        )

    return demo