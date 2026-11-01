"""
llm_node.

Builds the provider chat model (per runtime config), binds the approved MCP tools
(already resolved by mcp_manager before the graph was invoked), prepends the system
prompt (+ retrieved knowledge context if any), inlines image/audio attachments
(see services/media_resolver.py), and invokes the model. The built-in
generate_image tool is bound alongside the MCP tools.

The router (see builder.py conditional edge) inspects the returned AIMessage for
tool_calls to decide whether to go to hitl_gate, tool_exec_node, or end the turn.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import SystemMessage

from app.core.config import settings
from app.graphs.llm_providers import build_chat_model
from app.graphs.state import GraphState
from app.graphs.tools.image_tools import builtin_tools
from app.internal_tools.registry import get_internal_tools
from app.services.media_resolver import inline_media

_RAG_INSTRUCTIONS = """
## پاسخ‌گویی بر اساس اسناد
برای این گفتگو از پایگاه دانش جست‌وجو شده و نتایج در بخش «اسناد بازیابی‌شده» آمده است.
- پاسخ را فقط بر اساس همین اسناد بده. چیزی را که در اسناد نیست از خودت اضافه نکن و حدس نزن.
- اگر پاسخ در اسناد نیست، صریح بگو که در اسناد موجود اطلاعاتی درباره‌ی آن پیدا نشد.
- جدول‌ها را دقیق بخوان: هر مقدار را با سرستون و ردیف خودش تطبیق بده و اعداد و نام‌ها را عیناً نقل کن.
- منبعی که با «[تصویر]» شروع می‌شود، توضیح متنی یکی از تصاویر سند است.
- خط اول هر منبع (مثل «[منبع: نام فایل | صفحه ۳]») نشان می‌دهد محتوا از کجاست؛ در پایان پاسخ، منبع را به همین شکل ذکر کن.
- به زبان کاربر پاسخ بده.
"""

_RAG_NO_RESULTS = """
## پاسخ‌گویی بر اساس اسناد
برای این پرسش در پایگاه دانش جست‌وجو شد ولی هیچ محتوای مرتبطی پیدا نشد.
به کاربر صریح بگو که در اسناد موجود اطلاعاتی درباره‌ی این موضوع پیدا نکردی. از دانش عمومی خودت جواب نساز.
"""


async def llm_node(state: GraphState) -> dict[str, Any]:
    runtime = state["runtime"]

    model = build_chat_model(
        provider=runtime.get("model_provider"),
        model=runtime.get("model_name"),
        temperature=runtime.get("model_temperature", 0.7),
    )

    internal_tools = get_internal_tools(runtime)
    bound_tools = [*builtin_tools(), *(runtime.get("bound_tools") or []), *internal_tools.values()]
    if bound_tools:
        model = model.bind_tools(bound_tools)

    system_prompt = runtime.get("system_prompt") or "You are a helpful assistant."
    if runtime.get("skills_catalog"):  # level 1 of skills: names + descriptions only
        system_prompt = f"{system_prompt}\n\n{runtime['skills_catalog']}"

    # retrieved_context: None = no knowledge base on this request; "" = searched,
    # nothing found; str = sources (see knowledge_retrieval.py)
    context = state.get("retrieved_context")
    if context:
        system_prompt = f"{system_prompt}\n{_RAG_INSTRUCTIONS}\n## اسناد بازیابی‌شده\n{context}"
    elif context == "":
        system_prompt = f"{system_prompt}\n{_RAG_NO_RESULTS}"

    if settings.RAG_DEBUG:
        state_label = "NONE" if context is None else ("EMPTY" if context == "" else f"{len(context)} chars")
        print(f"[RAG DEBUG] llm_node context={state_label} model={runtime.get('model_provider')}/{runtime.get('model_name')}")

    history = await inline_media(state["messages"])
    messages = [SystemMessage(content=system_prompt), *history]
    ai_message = await model.ainvoke(messages)

    return {"messages": [ai_message]}