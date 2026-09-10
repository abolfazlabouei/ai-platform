import json

import gradio as gr

from clients.base import ApiError
from clients.chat_client import tool_approval_stream


def build_tool_approval_tab(token_state: gr.State):
    with gr.Tab("Tool Approval"):
        gr.Markdown(
            "When a `/chat/stream` event log shows `tool_approval_required`, resume the paused "
            "conversation here with your approve/reject decisions."
        )
        conversation_id = gr.Textbox(label="Conversation ID")
        decisions_json = gr.Textbox(
            label='Decisions JSON, e.g. {"tool_call_id_1": true, "tool_call_id_2": false}',
            lines=3,
            value='{"": true}',
        )
        submit_btn = gr.Button("Submit decisions", variant="primary")
        event_log = gr.Textbox(label="Resumed stream events", lines=12)

        def on_submit(token, conv_id, decisions_raw):
            try:
                decisions = json.loads(decisions_raw)
            except json.JSONDecodeError as e:
                yield f"Invalid JSON: {e}"
                return
            events = []
            try:
                for event_type, data in tool_approval_stream(token, conv_id, decisions):
                    events.append(f"[{event_type}] {data}")
                    yield "\n".join(events)
            except ApiError as e:
                events.append(str(e))
                yield "\n".join(events)

        submit_btn.click(on_submit, inputs=[token_state, conversation_id, decisions_json], outputs=[event_log])
