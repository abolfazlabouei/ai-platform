import gradio as gr

from ui.agents_tab import build_agents_tab
from ui.auth_tab import build_auth_tab
from ui.chat_tab import build_chat_tab
from ui.conversations_tab import build_conversations_tab
from ui.files_tab import build_files_tab
from ui.knowledge_tab import build_knowledge_tab
from ui.mcp_tab import build_mcp_tab
from ui.media_tab import build_media_tab
from ui.tool_approval_tab import build_tool_approval_tab

with gr.Blocks(title="ai-platform API test GUI") as demo:
    gr.Markdown("# ai-platform API test GUI\nA Gradio front-end for exercising the chat-agent, file-processing, and knowledge services.")
    token_state = gr.State("")

    build_auth_tab(token_state)
    build_chat_tab(token_state)
    build_agents_tab(token_state)
    build_conversations_tab(token_state)
    build_tool_approval_tab(token_state)
    build_mcp_tab(token_state)
    build_media_tab(token_state)
    build_files_tab(token_state)
    build_knowledge_tab(token_state)

if __name__ == "__main__":
    demo.queue().launch(server_name="0.0.0.0", server_port=7860)
