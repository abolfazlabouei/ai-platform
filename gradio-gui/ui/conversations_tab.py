import json

import gradio as gr

from clients.base import ApiError
from clients.chat_client import delete_conversation, get_conversation_messages, list_conversations


def _fmt(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def build_conversations_tab(token_state: gr.State):
    with gr.Tab("Conversations"):
        with gr.Row():
            limit = gr.Number(label="Limit", value=50, precision=0)
            offset = gr.Number(label="Offset", value=0, precision=0)
            list_btn = gr.Button("List conversations", variant="primary")
        conversations_box = gr.Code(label="Conversations", language="json")

        def on_list(token, limit, offset):
            try:
                return _fmt(list_conversations(token, int(limit), int(offset)))
            except ApiError as e:
                return str(e)

        list_btn.click(on_list, inputs=[token_state, limit, offset], outputs=[conversations_box])

        gr.Markdown("---")
        with gr.Row():
            conversation_id = gr.Textbox(label="Conversation ID")
            messages_limit = gr.Number(label="Messages limit", value=50, precision=0)
        with gr.Row():
            messages_btn = gr.Button("Get messages")
            delete_btn = gr.Button("Delete conversation", variant="stop")
        messages_box = gr.Code(label="Messages / result", language="json")

        def on_messages(token, conv_id, limit):
            try:
                return _fmt(get_conversation_messages(token, conv_id, int(limit)))
            except ApiError as e:
                return str(e)

        messages_btn.click(on_messages, inputs=[token_state, conversation_id, messages_limit], outputs=[messages_box])

        def on_delete(token, conv_id):
            try:
                delete_conversation(token, conv_id)
                return f"Deleted conversation {conv_id}"
            except ApiError as e:
                return str(e)

        delete_btn.click(on_delete, inputs=[token_state, conversation_id], outputs=[messages_box])
