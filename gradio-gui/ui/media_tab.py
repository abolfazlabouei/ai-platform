import json

import gradio as gr

from clients.base import ApiError
from clients.chat_client import get_media_url, upload_media


def _fmt(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def build_media_tab(token_state: gr.State):
    with gr.Tab("Media"):
        gr.Markdown("Upload a chat attachment (image/audio) and resolve its `media_id` to a presigned URL.")
        file_input = gr.File(label="File to upload")
        upload_btn = gr.Button("Upload", variant="primary")
        upload_result = gr.Code(label="Upload result", language="json")
        media_id_out = gr.Textbox(label="media_id (use this in a chat content block)")

        def on_upload(token, file):
            if file is None:
                return "No file selected.", ""
            try:
                with open(file.name, "rb") as f:
                    data = f.read()
                filename = file.name.split("/")[-1]
                result = upload_media(token, filename, data)
                return _fmt(result), result.get("file", {}).get("id", "")
            except ApiError as e:
                return str(e), ""

        upload_btn.click(on_upload, inputs=[token_state, file_input], outputs=[upload_result, media_id_out])

        gr.Markdown("---")
        media_id_lookup = gr.Textbox(label="media_id to resolve")
        resolve_btn = gr.Button("Resolve URL")
        resolve_result = gr.Code(label="Resolved", language="json")

        def on_resolve(token, media_id):
            try:
                return _fmt(get_media_url(token, media_id))
            except ApiError as e:
                return str(e)

        resolve_btn.click(on_resolve, inputs=[token_state, media_id_lookup], outputs=[resolve_result])
