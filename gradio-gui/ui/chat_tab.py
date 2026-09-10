import gradio as gr

from clients.base import ApiError
from clients.chat_client import chat_complete, chat_stream


def _split_ids(raw: str) -> list:
    return [x.strip() for x in raw.split(",") if x.strip()]


def build_chat_tab(token_state: gr.State):
    with gr.Tab("Chat (ad-hoc)"):
        gr.Markdown(
            "Exercise `/chat/complete` and `/chat/stream`. Set **Clinic ID** to test the "
            "doctor-laser clinic-context injection feature."
        )
        with gr.Row():
            with gr.Column(scale=2):
                # type="tuples" (not the newer "messages" dict format): gradio
                # 5.9.1's api-schema introspection crashes on the "messages"
                # format's metadata field (TypeError: argument of type 'bool'
                # is not iterable, from an additionalProperties:true schema).
                chatbot = gr.Chatbot(type="tuples", height=420)
                message = gr.Textbox(label="Message", lines=2)
                with gr.Row():
                    stream_btn = gr.Button("Send (stream)", variant="primary")
                    complete_btn = gr.Button("Send (complete)")
                event_log = gr.Textbox(label="Event log (tool calls / approvals / errors)", lines=6)
            with gr.Column(scale=1):
                conversation_id = gr.Textbox(label="Conversation ID (blank = new)")
                clinic_id = gr.Textbox(label="Clinic ID (doctor-laser context)")
                mcp_server_ids = gr.Textbox(label="MCP server IDs (comma-separated)")
                knowledge_base_ids = gr.Textbox(label="Knowledge base IDs (comma-separated)")
                model_provider = gr.Textbox(label="Model provider (optional)")
                model_name = gr.Textbox(label="Model name (optional)")

        def _common_kwargs(conv_id, clinic, mcp_ids, kb_ids, provider, model):
            return dict(
                conversation_id=conv_id or None,
                mcp_server_ids=_split_ids(mcp_ids),
                knowledge_base_ids=_split_ids(kb_ids),
                model_provider=provider or None,
                model_name=model or None,
                clinic_id=clinic or None,
            )

        def on_complete(token, history, text, conv_id, clinic, mcp_ids, kb_ids, provider, model):
            history = history or []
            try:
                result = chat_complete(
                    token, content_text=text, **_common_kwargs(conv_id, clinic, mcp_ids, kb_ids, provider, model)
                )
                reply = "\n".join(b.get("text", "") for b in result.get("content_blocks", []) if b.get("type") == "text")
                history.append((text, reply or "(no text content)"))
                new_conv_id = result.get("conversation_id", conv_id)
                return history, "", new_conv_id, f"conversation_id: {new_conv_id}"
            except ApiError as e:
                history.append((text, f"ERROR: {e}"))
                return history, "", conv_id, str(e)

        complete_btn.click(
            on_complete,
            inputs=[token_state, chatbot, message, conversation_id, clinic_id, mcp_server_ids, knowledge_base_ids, model_provider, model_name],
            outputs=[chatbot, message, conversation_id, event_log],
        )

        def on_stream(token, history, text, conv_id, clinic, mcp_ids, kb_ids, provider, model):
            history = history or []
            history.append([text, ""])
            events = []
            try:
                for event_type, data in chat_stream(
                    token, content_text=text, **_common_kwargs(conv_id, clinic, mcp_ids, kb_ids, provider, model)
                ):
                    if event_type == "token":
                        history[-1][1] += data.get("text", "")
                        yield history, "", conv_id, "\n".join(events)
                    elif event_type == "tool_call":
                        events.append(f"[tool_call] {data.get('tool_name')} input={data.get('input')}")
                        yield history, "", conv_id, "\n".join(events)
                    elif event_type == "tool_result":
                        events.append(f"[tool_result] {data.get('tool_name')} output={data.get('output')}")
                        yield history, "", conv_id, "\n".join(events)
                    elif event_type == "tool_approval_required":
                        events.append(f"[tool_approval_required] {data.get('tool_calls')}")
                        yield history, "", conv_id, "\n".join(events)
                    elif event_type == "error":
                        events.append(f"[error] {data.get('message')}")
                        yield history, "", conv_id, "\n".join(events)
                    elif event_type == "done":
                        events.append("[done]")
                        yield history, "", conv_id, "\n".join(events)
            except ApiError as e:
                history[-1][1] += f"\nERROR: {e}"
                yield history, "", conv_id, "\n".join(events + [str(e)])

        stream_btn.click(
            on_stream,
            inputs=[token_state, chatbot, message, conversation_id, clinic_id, mcp_server_ids, knowledge_base_ids, model_provider, model_name],
            outputs=[chatbot, message, conversation_id, event_log],
        )
