import json

import gradio as gr

from clients.base import ApiError
from clients.files_client import (
    delete_file,
    get_download_url,
    get_file,
    get_file_chunks,
    get_job_status,
    list_files,
    upload_document,
)


def _fmt(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def build_files_tab(token_state: gr.State):
    with gr.Tab("Files (file-processing-service)"):
        gr.Markdown("Upload `.docx`, `.pdf`, `.xlsx`/`.xlsm`, or `.md` documents. Max 100MB.")
        file_input = gr.File(label="Document to upload")
        upload_btn = gr.Button("Upload", variant="primary")
        upload_result = gr.Code(label="Upload result", language="json")
        file_id_out = gr.Textbox(label="file.id")
        job_id_state = gr.State("")

        def on_upload(token, file):
            if file is None:
                return "No file selected.", "", ""
            try:
                with open(file.name, "rb") as f:
                    data = f.read()
                filename = file.name.split("/")[-1]
                result = upload_document(token, filename, data)
                return _fmt(result), result.get("file", {}).get("id", ""), result.get("job_id", "")
            except ApiError as e:
                return str(e), "", ""

        upload_btn.click(on_upload, inputs=[token_state, file_input], outputs=[upload_result, file_id_out, job_id_state])

        gr.Markdown("### Job progress")
        job_status_box = gr.Code(label="Job status", language="json")
        poll_timer = gr.Timer(2.0, active=False)

        def start_polling(job_id):
            return gr.Timer(active=bool(job_id))

        job_id_state.change(start_polling, inputs=[job_id_state], outputs=[poll_timer])

        def on_tick(token, job_id):
            if not job_id:
                return "", gr.Timer(active=False)
            try:
                status = get_job_status(token, job_id)
                still_running = status.get("stage") not in ("done", "failed")
                return _fmt(status), gr.Timer(active=still_running)
            except ApiError as e:
                return str(e), gr.Timer(active=False)

        poll_timer.tick(on_tick, inputs=[token_state, job_id_state], outputs=[job_status_box, poll_timer])

        gr.Markdown("---\n### Manage files")
        with gr.Row():
            file_id = gr.Textbox(label="File ID")
            with gr.Column():
                get_btn = gr.Button("Get metadata")
                list_btn = gr.Button("List all files")
                chunks_btn = gr.Button("Get chunks")
                download_btn = gr.Button("Get download URL")
                delete_btn = gr.Button("Delete file", variant="stop")
        result_box = gr.Code(label="Result", language="json")

        get_btn.click(lambda t, fid: _safe(get_file, t, fid), inputs=[token_state, file_id], outputs=[result_box])
        list_btn.click(lambda t: _safe(list_files, t), inputs=[token_state], outputs=[result_box])
        chunks_btn.click(lambda t, fid: _safe(get_file_chunks, t, fid), inputs=[token_state, file_id], outputs=[result_box])
        download_btn.click(lambda t, fid: _safe(get_download_url, t, fid), inputs=[token_state, file_id], outputs=[result_box])

        def on_delete(token, fid):
            try:
                delete_file(token, fid)
                return f"Deleted file {fid}"
            except ApiError as e:
                return str(e)

        delete_btn.click(on_delete, inputs=[token_state, file_id], outputs=[result_box])


def _safe(fn, *args):
    try:
        return _fmt(fn(*args))
    except ApiError as e:
        return str(e)
