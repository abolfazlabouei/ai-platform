import json

import gradio as gr

from clients.base import ApiError
from clients.knowledge_client import (
    create_kb,
    delete_kb,
    get_job_status,
    get_kb,
    get_kb_sources,
    ingest_files,
    list_kbs,
    search,
)


def _fmt(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def _safe(fn, *args):
    try:
        return _fmt(fn(*args))
    except ApiError as e:
        return str(e)


def build_knowledge_tab(token_state: gr.State):
    with gr.Tab("Knowledge Bases (knowledge-service)"):
        with gr.Row():
            with gr.Column():
                kb_name = gr.Textbox(label="Name")
                kb_description = gr.Textbox(label="Description")
                create_btn = gr.Button("Create knowledge base", variant="primary")
            with gr.Column():
                kb_id = gr.Textbox(label="Knowledge base ID")
                with gr.Row():
                    get_btn = gr.Button("Get")
                    list_btn = gr.Button("List all")
                    sources_btn = gr.Button("Get sources")
                    delete_btn = gr.Button("Delete", variant="stop")
        result_box = gr.Code(label="Result", language="json")

        def on_create(token, name, desc):
            try:
                kb = create_kb(token, name, desc)
                return _fmt(kb), kb.get("id", "")
            except ApiError as e:
                return str(e), ""

        create_btn.click(on_create, inputs=[token_state, kb_name, kb_description], outputs=[result_box, kb_id])

        get_btn.click(lambda t, k: _safe(get_kb, t, k), inputs=[token_state, kb_id], outputs=[result_box])
        list_btn.click(lambda t: _safe(list_kbs, t), inputs=[token_state], outputs=[result_box])
        sources_btn.click(lambda t, k: _safe(get_kb_sources, t, k), inputs=[token_state, kb_id], outputs=[result_box])

        def on_delete(token, k):
            try:
                delete_kb(token, k)
                return f"Deleted knowledge base {k}"
            except ApiError as e:
                return str(e)

        delete_btn.click(on_delete, inputs=[token_state, kb_id], outputs=[result_box])

        gr.Markdown("---\n### Ingest already-uploaded files")
        with gr.Row():
            ingest_kb_id = gr.Textbox(label="Knowledge base ID")
            ingest_file_ids = gr.Textbox(label="File IDs (comma-separated, from the Files tab)")
        ingest_btn = gr.Button("Ingest files")
        ingest_result = gr.Code(label="Ingest jobs", language="json")

        def on_ingest(token, kbid, file_ids_raw):
            file_ids = [x.strip() for x in file_ids_raw.split(",") if x.strip()]
            try:
                return _fmt(ingest_files(token, kbid, file_ids))
            except ApiError as e:
                return str(e)

        ingest_btn.click(on_ingest, inputs=[token_state, ingest_kb_id, ingest_file_ids], outputs=[ingest_result])

        gr.Markdown("Check an ingest job's status:")
        with gr.Row():
            ingest_job_id = gr.Textbox(label="Job ID")
            job_status_btn = gr.Button("Check status")
        job_status_box = gr.Code(label="Job status", language="json")
        job_status_btn.click(
            lambda t, j: _safe(get_job_status, t, j), inputs=[token_state, ingest_job_id], outputs=[job_status_box]
        )

        gr.Markdown("---\n### Search")
        with gr.Row():
            search_kb_ids = gr.Textbox(label="Knowledge base IDs (comma-separated)")
            search_query = gr.Textbox(label="Query")
            top_k = gr.Number(label="Top K", value=6, precision=0)
        search_btn = gr.Button("Search", variant="primary")
        search_result = gr.Code(label="Results", language="json")

        def on_search(token, kb_ids_raw, query, k):
            kb_ids = [x.strip() for x in kb_ids_raw.split(",") if x.strip()]
            try:
                return _fmt(search(token, kb_ids, query, int(k)))
            except ApiError as e:
                return str(e)

        search_btn.click(on_search, inputs=[token_state, search_kb_ids, search_query, top_k], outputs=[search_result])
