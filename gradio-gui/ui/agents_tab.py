import json

import gradio as gr

from clients.base import ApiError
from clients.chat_client import (
    agent_chat_complete,
    agent_chat_stream,
    create_agent,
    delete_agent,
    get_agent,
    list_agents,
)


def _fmt(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def build_agents_tab(token_state: gr.State):
    with gr.Tab("Agents"):
        with gr.Accordion("Create / list / manage agents", open=True):
            with gr.Row():
                with gr.Column():
                    name = gr.Textbox(label="Name")
                    description = gr.Textbox(label="Description")
                    system_prompt = gr.Textbox(label="System prompt", lines=4)
                    with gr.Row():
                        provider = gr.Textbox(label="Model provider", value="anthropic")
                        model = gr.Textbox(label="Model", value="claude-sonnet-4-6")
                        temperature = gr.Number(label="Temperature", value=0.7)
                    mcp_server_ids = gr.Textbox(label="MCP server IDs (comma-separated)")
                    knowledge_base_ids = gr.Textbox(label="Knowledge base IDs (comma-separated)")
                    capabilities = gr.Textbox(label="Capabilities (comma-separated)")
                    is_composable = gr.Checkbox(label="Is composable")
                    create_btn = gr.Button("Create agent", variant="primary")
                with gr.Column():
                    agent_id = gr.Textbox(label="Agent ID (for get/update/delete/chat)")
                    with gr.Row():
                        get_btn = gr.Button("Get")
                        list_btn = gr.Button("List all")
                        delete_btn = gr.Button("Delete", variant="stop")
                    result_box = gr.Code(label="Result", language="json")

        def split_ids(raw):
            return [x.strip() for x in raw.split(",") if x.strip()]

        def on_create(token, name, desc, prompt, provider, model, temp, mcp_ids, kb_ids, caps, composable):
            try:
                agent = create_agent(
                    token,
                    {
                        "name": name,
                        "description": desc,
                        "system_prompt": prompt,
                        "model_config": {"provider": provider, "model": model, "temperature": temp},
                        "mcp_server_ids": split_ids(mcp_ids),
                        "knowledge_base_ids": split_ids(kb_ids),
                        "tool_policy": [],
                        "capabilities": split_ids(caps),
                        "is_composable": composable,
                    },
                )
                return _fmt(agent), agent.get("id", "")
            except ApiError as e:
                return str(e), ""

        create_btn.click(
            on_create,
            inputs=[token_state, name, description, system_prompt, provider, model, temperature, mcp_server_ids, knowledge_base_ids, capabilities, is_composable],
            outputs=[result_box, agent_id],
        )

        def on_get(token, aid):
            try:
                return _fmt(get_agent(token, aid))
            except ApiError as e:
                return str(e)

        get_btn.click(on_get, inputs=[token_state, agent_id], outputs=[result_box])

        def on_list(token):
            try:
                return _fmt(list_agents(token))
            except ApiError as e:
                return str(e)

        list_btn.click(on_list, inputs=[token_state], outputs=[result_box])

        def on_delete(token, aid):
            try:
                delete_agent(token, aid)
                return f"Deleted agent {aid}"
            except ApiError as e:
                return str(e)

        delete_btn.click(on_delete, inputs=[token_state, agent_id], outputs=[result_box])

        gr.Markdown("---\n### Chat with an agent")
        with gr.Row():
            with gr.Column(scale=2):
                agent_chatbot = gr.Chatbot(type="messages", height=360)
                agent_message = gr.Textbox(label="Message", lines=2)
                with gr.Row():
                    agent_stream_btn = gr.Button("Send (stream)", variant="primary")
                    agent_complete_btn = gr.Button("Send (complete)")
            with gr.Column(scale=1):
                agent_chat_id = gr.Textbox(label="Agent ID")
                agent_conversation_id = gr.Textbox(label="Conversation ID (blank = new)")

        def on_agent_complete(token, history, text, aid, conv_id):
            history = history or []
            history.append({"role": "user", "content": text})
            try:
                result = agent_chat_complete(token, aid, text, conv_id or None)
                reply = "\n".join(b.get("text", "") for b in result.get("content_blocks", []) if b.get("type") == "text")
                history.append({"role": "assistant", "content": reply or "(no text content)"})
                return history, "", result.get("conversation_id", conv_id)
            except ApiError as e:
                history.append({"role": "assistant", "content": f"ERROR: {e}"})
                return history, "", conv_id

        agent_complete_btn.click(
            on_agent_complete,
            inputs=[token_state, agent_chatbot, agent_message, agent_chat_id, agent_conversation_id],
            outputs=[agent_chatbot, agent_message, agent_conversation_id],
        )

        def on_agent_stream(token, history, text, aid, conv_id):
            history = history or []
            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": ""})
            try:
                for event_type, data in agent_chat_stream(token, aid, text, conv_id or None):
                    if event_type == "token":
                        history[-1]["content"] += data.get("text", "")
                        yield history, "", conv_id
                    elif event_type == "error":
                        history[-1]["content"] += f"\n[error] {data.get('message')}"
                        yield history, "", conv_id
            except ApiError as e:
                history[-1]["content"] += f"\nERROR: {e}"
                yield history, "", conv_id

        agent_stream_btn.click(
            on_agent_stream,
            inputs=[token_state, agent_chatbot, agent_message, agent_chat_id, agent_conversation_id],
            outputs=[agent_chatbot, agent_message, agent_conversation_id],
        )
