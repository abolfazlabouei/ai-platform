import json

import gradio as gr

from clients.base import ApiError
from clients.chat_client import (
    create_mcp_server,
    delete_mcp_server,
    list_mcp_server_tools,
    list_mcp_servers,
    test_mcp_server_connection,
    update_mcp_tool,
)


def _fmt(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def build_mcp_tab(token_state: gr.State):
    with gr.Tab("MCP Servers"):
        with gr.Row():
            with gr.Column():
                name = gr.Textbox(label="Name")
                transport = gr.Dropdown(label="Transport", choices=["sse", "stdio", "streamable_http"], value="sse")
                url = gr.Textbox(label="URL")
                auth_type = gr.Dropdown(label="Auth type", choices=["none", "bearer"], value="none")
                auth_token = gr.Textbox(label="Auth token (if bearer)")
                create_btn = gr.Button("Create MCP server", variant="primary")
            with gr.Column():
                server_id = gr.Textbox(label="Server ID")
                with gr.Row():
                    list_btn = gr.Button("List servers")
                    list_tools_btn = gr.Button("List tools")
                    test_btn = gr.Button("Test connection")
                    delete_btn = gr.Button("Delete server", variant="stop")
                result_box = gr.Code(label="Result", language="json")

        def on_create(token, name, transport, url, auth_type, auth_token):
            auth_config = {"type": auth_type}
            if auth_type == "bearer":
                auth_config["token"] = auth_token
            try:
                server = create_mcp_server(
                    token, {"name": name, "transport": transport, "url": url, "auth_config": auth_config}
                )
                return _fmt(server), server.get("id", "")
            except ApiError as e:
                return str(e), ""

        create_btn.click(
            on_create,
            inputs=[token_state, name, transport, url, auth_type, auth_token],
            outputs=[result_box, server_id],
        )

        def on_list(token):
            try:
                return _fmt(list_mcp_servers(token))
            except ApiError as e:
                return str(e)

        list_btn.click(on_list, inputs=[token_state], outputs=[result_box])

        def on_list_tools(token, sid):
            try:
                return _fmt(list_mcp_server_tools(token, sid))
            except ApiError as e:
                return str(e)

        list_tools_btn.click(on_list_tools, inputs=[token_state, server_id], outputs=[result_box])

        def on_test(token, sid):
            try:
                return _fmt(test_mcp_server_connection(token, sid))
            except ApiError as e:
                return str(e)

        test_btn.click(on_test, inputs=[token_state, server_id], outputs=[result_box])

        def on_delete(token, sid):
            try:
                delete_mcp_server(token, sid)
                return f"Deleted MCP server {sid}"
            except ApiError as e:
                return str(e)

        delete_btn.click(on_delete, inputs=[token_state, server_id], outputs=[result_box])

        gr.Markdown("---\n### Approve / reject a discovered tool")
        with gr.Row():
            tool_server_id = gr.Textbox(label="Server ID")
            tool_id = gr.Textbox(label="Tool ID")
            approval_status = gr.Dropdown(label="Approval status", choices=["approved", "rejected", "pending"], value="approved")
            requires_hitl = gr.Checkbox(label="Requires human approval per call")
        approve_btn = gr.Button("Update tool")
        approve_result = gr.Code(label="Result", language="json")

        def on_approve(token, sid, tid, status, hitl):
            try:
                return _fmt(update_mcp_tool(token, sid, tid, {"approval_status": status, "requires_hitl": hitl}))
            except ApiError as e:
                return str(e)

        approve_btn.click(
            on_approve,
            inputs=[token_state, tool_server_id, tool_id, approval_status, requires_hitl],
            outputs=[approve_result],
        )
