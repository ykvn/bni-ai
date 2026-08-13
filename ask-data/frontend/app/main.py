import os
import time
import json
import requests
import sqlparse
from datetime import datetime
import pandas as pd
import gradio as gr

from shared.cml_auth import build_cml_headers


def format_sql(raw_sql: str) -> str:
    """Formats a raw single-line SQL string into clean multi-line SQL."""
    if not raw_sql or not raw_sql.strip():
        return ""
    try:
        return sqlparse.format(
            raw_sql.strip(),
            reindent=True,
            keyword_case="upper",
            comma_first=False,
            indent_width=2
        )
    except Exception:
        return raw_sql.strip()


def parse_payload_to_ui(payload: dict):
    """Parses payload into text components and a Pandas DataFrame for UI rendering."""
    text_parts = []
    df_update = gr.update(visible=False, value=None)

    if not isinstance(payload, dict):
        return str(payload), df_update

    # 1. Natural Language Response
    if payload.get("response"):
        text_parts.append(payload["response"])

    # 2. Formatted SQL Code Block (Replaces single-line SQL with multi-line formatted SQL)
    if payload.get("predicted_sql"):
        formatted_sql = format_sql(payload["predicted_sql"])
        text_parts.append(f"### 🤖 Generated SQL:\n```sql\n{formatted_sql}\n```")

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
        elif isinstance(data, list) and len(data) == 0 and payload.get("type") == "SQL":
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
        elif status_upper == "CANCELLED":
            badge = "🚫 CANCELLED"
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

    def make_tab_handlers():
        """
        Builds an isolated pair (ask/cancel) of handler generators for a single tab.
        Each tab gets its own job_id / cancel-flag state so switching tabs or
        cancelling one tab never affects the other tab's running job.
        """
        state = {"job_id": None, "cancel": False}

        def ask_backend(question: str, qtype: str):
            state["cancel"] = False

            if not question.strip():
                yield (
                    gr.update(visible=False, value=""),
                    "Please enter a valid question.",
                    gr.update(visible=False),
                    gr.update(interactive=True),
                    gr.update(visible=False, interactive=False)
                )
                return

            start_time = time.time()

            # Initial yield before network dispatch
            initial_job_box = (
                f"### Job Execution Information\n"
                f"- **Job ID:** `Submitting...`\n"
                f"- **Status:** ⏳ ENQUEUEING\n"
                f"- **Current Time:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
                f"⏳ Submitting question to CrewAI Engine..."
            )
            yield (
                gr.update(visible=True, value=initial_job_box),
                "",
                gr.update(visible=False),
                gr.update(interactive=False),
                gr.update(visible=True, interactive=True)
            )

            try:
                headers = build_cml_headers(extra={"Content-Type": "application/json", "accept": "application/json"})

                response = requests.post(
                    backend_url,
                    json={"type": qtype, "question": question},
                    headers=headers,
                    timeout=30,
                    verify=False
                )
                response.raise_for_status()
                payload = response.json()

                if "job_id" in payload:
                    job_id = payload["job_id"]
                    state["job_id"] = job_id
                    job_status_url = f"{base_api_url}/job/{job_id}"

                    while True:
                        time.sleep(1.0)

                        if state["cancel"]:
                            job_box_cancelled = format_job_info(job_id, "CANCELLED", start_time, is_final=True)
                            yield (
                                gr.update(visible=True, value=job_box_cancelled),
                                "❌ Request was cancelled by user.",
                                gr.update(visible=False),
                                gr.update(interactive=True),
                                gr.update(visible=False, interactive=False)
                            )
                            state["cancel"] = False
                            break

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
                                gr.update(interactive=True),
                                gr.update(visible=False, interactive=False)
                            )
                            break

                        elif status == "failed":
                            error_msg = job_data.get("error", "Unknown error encountered.")
                            job_box_failed = format_job_info(job_id, "FAILED", start_time, is_final=True)
                            yield (
                                gr.update(visible=True, value=job_box_failed),
                                f"❌ Task Failed:\n{error_msg}",
                                gr.update(visible=False),
                                gr.update(interactive=True),
                                gr.update(visible=False, interactive=False)
                            )
                            break

                        elif status == "cancelled":
                            job_box_cancelled = format_job_info(job_id, "CANCELLED", start_time, is_final=True)
                            yield (
                                gr.update(visible=True, value=job_box_cancelled),
                                "❌ Request was cancelled.",
                                gr.update(visible=False),
                                gr.update(interactive=True),
                                gr.update(visible=False, interactive=False)
                            )
                            break

                        else:
                            job_box_running = format_job_info(job_id, status, start_time, is_final=False)
                            job_box_running += "\n⏳ CrewAI is currently executing your request..."
                            yield (
                                gr.update(visible=True, value=job_box_running),
                                "",
                                gr.update(visible=False),
                                gr.update(interactive=False),
                                gr.update(visible=True, interactive=True)
                            )
                else:
                    text_out, df_out = parse_payload_to_ui(payload)
                    job_box_direct = format_job_info("N/A (Direct)", "SUCCESS", start_time, is_final=True)
                    yield (
                        gr.update(visible=True, value=job_box_direct),
                        text_out,
                        df_out,
                        gr.update(interactive=True),
                        gr.update(visible=False, interactive=False)
                    )

            except Exception as exc:
                error_details = str(exc) if str(exc) and str(exc) != "0" else repr(exc)
                job_box_err = format_job_info("ERROR", "FAILED", start_time, is_final=True)
                yield (
                    gr.update(visible=True, value=job_box_err),
                    f"❌ Exception Error:\n{error_details}",
                    gr.update(visible=False),
                    gr.update(interactive=True),
                    gr.update(visible=False, interactive=False)
                )

        def cancel_backend():
            state["cancel"] = True
            job_id = state["job_id"]
            if job_id:
                try:
                    headers = build_cml_headers(extra={"Content-Type": "application/json", "accept": "application/json"})
                    cancel_url = f"{base_api_url}/job/{job_id}/cancel"
                    requests.delete(cancel_url, headers=headers, timeout=10, verify=False)
                except Exception as e:
                    print(f"Cancel request error: {e}", flush=True)
            return (
                gr.update(visible=True, value="### Job Execution Information\n⏳ Cancelling request..."),
                "",
                gr.update(visible=False),
                gr.update(interactive=True),
                gr.update(visible=False, interactive=False)
            )

        return ask_backend, cancel_backend

    with gr.Blocks(title="Bank Negara Indonesia Q&A") as demo:
        gr.Markdown("# Bank Negara Indonesia Zero Query Assistant")
        gr.Markdown("Ask questions about bank data (SQL) or retrieve answers from policy documents (RAG).")

        # ---------------- SQL Question tab ----------------
        with gr.Tab("SQL Question"):
            gr.Markdown("### 🧮 Zero SQL Assistant\nAsk for aggregates, balances, or reports. The question is converted to SQL and executed against the data warehouse.")
            sql_question = gr.Textbox(label="Question", lines=3, placeholder="e.g. Berapa total simpanan nasabah di Surabaya bulan ini?")
            sql_type = gr.State("sql")

            with gr.Row():
                sql_submit_btn = gr.Button("Ask")
                sql_cancel_btn = gr.Button("Cancel", visible=False)

            sql_job_info_box = gr.Markdown(visible=False)
            sql_output_text = gr.Markdown(label="Answer & SQL")
            sql_output_table = gr.Dataframe(label="Query Results", visible=False, interactive=False)

            sql_ask, sql_cancel = make_tab_handlers()

            sql_submit_btn.click(
                fn=sql_ask,
                inputs=[sql_question, sql_type],
                outputs=[sql_job_info_box, sql_output_text, sql_output_table, sql_submit_btn, sql_cancel_btn],
                concurrency_limit=None,
                show_progress="hidden"
            )
            sql_cancel_btn.click(
                fn=sql_cancel,
                inputs=None,
                outputs=[sql_job_info_box, sql_output_text, sql_output_table, sql_submit_btn, sql_cancel_btn],
                concurrency_limit=None,
                show_progress="hidden"
            )

        # ---------------- RAG Question tab ----------------
        with gr.Tab("RAG Question"):
            gr.Markdown("### 📄 Policy & Knowledge Retrieval Assistant\nAsk about manuals, SOPs, criteria, and regulations. Answers are retrieved from enterprise documents.")
            rag_question = gr.Textbox(label="Question", lines=3, placeholder="e.g. Apa saja kriteria yang harus dipenuhi untuk persetujuan kredit?")
            rag_type = gr.State("rag")

            with gr.Row():
                rag_submit_btn = gr.Button("Ask")
                rag_cancel_btn = gr.Button("Cancel", visible=False)

            rag_job_info_box = gr.Markdown(visible=False)
            rag_output_text = gr.Textbox(label="Answer", lines=12, interactive=False)
            rag_output_table = gr.Dataframe(label="Query Results", visible=False, interactive=False)

            rag_ask, rag_cancel = make_tab_handlers()

            rag_submit_btn.click(
                fn=rag_ask,
                inputs=[rag_question, rag_type],
                outputs=[rag_job_info_box, rag_output_text, rag_output_table, rag_submit_btn, rag_cancel_btn],
                concurrency_limit=None,
                show_progress="hidden"
            )
            rag_cancel_btn.click(
                fn=rag_cancel,
                inputs=None,
                outputs=[rag_job_info_box, rag_output_text, rag_output_table, rag_submit_btn, rag_cancel_btn],
                concurrency_limit=None,
                show_progress="hidden"
            )

    return demo