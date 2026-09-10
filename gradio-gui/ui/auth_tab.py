import gradio as gr

from clients.auth_client import DEFAULT_SECRET, generate_dev_token


def build_auth_tab(token_state: gr.State):
    with gr.Tab("Auth"):
        gr.Markdown(
            "Generate a dev JWT (same shared secret used by all three services) "
            "or paste a token issued elsewhere. It's stored for this browser session "
            "and used as the `Authorization: Bearer <token>` header on every call below."
        )
        with gr.Row():
            user_id = gr.Textbox(label="User ID", value="demo-user-1")
            secret = gr.Textbox(label="JWT secret", value=DEFAULT_SECRET)
            expires_hours = gr.Number(label="Expires (hours)", value=24, precision=0)
        generate_btn = gr.Button("Generate dev token", variant="primary")
        token_box = gr.Textbox(label="Bearer token", lines=3, show_copy_button=True)
        status = gr.Markdown()

        def on_generate(uid, sec, hours):
            token = generate_dev_token(uid, sec, hours)
            return token, token, "Token generated and set as active."

        generate_btn.click(
            on_generate,
            inputs=[user_id, secret, expires_hours],
            outputs=[token_box, token_state, status],
        )

        def on_manual_change(token):
            return token, "Active token updated."

        token_box.change(on_manual_change, inputs=[token_box], outputs=[token_state, status])
