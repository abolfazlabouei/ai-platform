# AI Platform — Architecture

معماری میکروسرویس برای پلتفرم Chat/Agent با قابلیت گسترش به Channel Gateway ها (تلگرام، واتس‌اپ) و Multi-Agent Orchestration در آینده.

---

## 1. نمای کلی

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ telegram-gw   │   │ whatsapp-gw   │   │  web-gw (BFF) │   ← Channel Gateways (future)
│ [FUTURE]      │   │ [FUTURE]      │   │               │
└──────┬────────┘   └──────┬────────┘   └──────┬────────┘
       │                   │                   │
       └─────────┬─────────┴─────────┬─────────┘
                  │  Channel Contract (content_blocks[] + ChannelIdentity) │
                  ▼
     ┌─────────────────────────────────┐
     │       chat-agent-service          │  ← LangGraph runtime: chat + agents + MCP + HITL
     └───────────────┬─────────────────┘
                      │ agent registry API (GET /agents?is_composable=true)
     ┌───────────────▼─────────────────┐
     │  multi-agent-orchestrator-service  │  ← [FUTURE] Supervisor graph, agent-to-agent
     └─────────────────────────────────┘

     ┌─────────────────────┐      ┌─────────────────────┐
     │ file-processing-svc  │─────▶│  knowledge-service    │
     │ (extract + chunk)     │      │ (embed + vector search)│
     └─────────────────────┘      └─────────────────────┘

Shared infra: Postgres (per-service DB) | Redis (pub/sub, celery broker) |
              Object Storage (MinIO/S3) | Vector DB (Qdrant)
```

اصل طراحی: هر سرویس دیتابیس/schema مجزا داره. ارتباط بین سرویس‌ها فقط از طریق HTTP قراردادی یا Redis pub/sub (برای پیشرفت job). یک پکیج مشترک `shared-schemas` بین همه سرویس‌ها import میشه تا فرمت content block / message / chunk / agent-card همیشه یکسان بمونه.

---

## 2. chat-agent-service

### مدل داده

```
Conversation
 ├── id (uuid)              ← thread_id برای LangGraph checkpointer
 ├── user_id
 ├── agent_id (nullable)     ← null یعنی چت عادی (ad-hoc)
 ├── mode: "ad_hoc" | "agent"
 ├── channel: "web" | "telegram" | "whatsapp" | "api"
 ├── channel_identity_id (nullable, FK)
 ├── runtime_config (jsonb)  ← ad-hoc: mcp_server_ids[], knowledge_ids[], model
 └── created_at / updated_at

Message
 ├── id, conversation_id, role
 ├── content_blocks (jsonb[])  ← text | image | audio | tool_call | tool_result | generated_image
 └── created_at

Agent
 ├── id, name, description
 ├── system_prompt
 ├── model_config { provider, model, temperature, ... }
 ├── mcp_server_ids[], knowledge_base_ids[]
 ├── tool_policy: [{server_id, tool_name, status, requires_hitl}]
 ├── capabilities: []          ← برای Agent Registry (multi-agent آینده)
 └── is_composable: bool       ← اجازه صدا زده شدن به‌عنوان sub-agent

McpServer / McpTool
 ├── server: id, name, transport, url, auth_config, status
 └── tool: id, server_id, tool_name, input_schema, approval_status(pending|approved|rejected), requires_hitl

ChannelIdentity   ← پل بین کاربر پلتفرم خارجی و کاربر داخلی
 ├── id, user_id, channel, external_id, metadata
```

History دو لایه نگه‌داری میشه: **LangGraph checkpointer** (Postgres، برای state/resume گراف) + **جدول Message** (برای لیست‌کردن، جستجو، pagination در UI).

### گراف پارامتری (LangGraph)

یک `graph_builder(mode, model_config, mcp_tools, kb_ids, system_prompt)` مشترک بین چت عادی و agent:

```
input_normalizer → [knowledge_retrieval?] → llm_node
                                                │
                              ┌─────────────────┼──────────────────┐
                              ▼                 ▼                  ▼
                        tool_exec_node     hitl_gate (interrupt)   sub_agent_caller
                              │                 │  (future hook)        │
                              └──────► llm_node ◄┴───────────────────────┘
```

- `/chat/stream` → `graph.astream_events()` → SSE
- `/chat/complete` → `graph.ainvoke()`
- `hitl_gate`: اگر tool فراخوانی‌شده `requires_hitl=true` داشته باشه، گراف با `interrupt()` متوقف میشه، event `tool_approval_required` به فرانت میره؛ با `POST /conversations/{id}/tool-approval` از همون checkpoint resume میشه.
- `sub_agent_caller`: هوک برای آینده — یک Agent دیگه رو از طریق `/agents/{id}/chat/complete` مثل یک tool صدا میزنه (برای وقتی multi-agent-orchestrator اضافه بشه).

### چندوجهی (Multimodal)

- ورودی: عکس/صوت اول در `file-processing-service` آپلود میشه (`media_id`/URL برمی‌گرده)، چت فقط رفرنس رو می‌فرسته — نه base64 خام داخل JSON.
- خروجی (عکس تولیدشده): در object storage ذخیره و URL + یک `thumbnail_base64` کوچیک برای پیش‌نمایش فوری برگردونده میشه (نه base64 کامل، مگر `?format=base64` صراحتاً خواسته بشه).

### MCP + HITL

1. `POST /mcp-servers` ثبت سرور
2. `POST /mcp-servers/{id}/test-connection` → اتصال + کشف و کش تولزها (status=pending)
3. کاربر هر tool رو approve/reject می‌کنه + `requires_hitl` رو مشخص می‌کنه
4. فقط تولزهای approved به مدل bind میشن؛ تولزهای `requires_hitl=true` از `hitl_gate` رد میشن.

---

## 3. file-processing-service

آپلود → ذخیره raw file در object storage → Celery task غیرمسدودکننده (`job_id` فوری برمی‌گرده) → مراحل `extracting → chunking → done/failed` که هرکدوم پیشرفتشون در کانال Redis `job:{job_id}` publish میشه → API با SSE از همون کانال subscribe و forward می‌کنه.

Extractor ها: `docx` (پاراگراف + جدول + عکس embedded از طریق پیمایش zip داخلی `word/media/`)، `pdf` (متن/جدول/عکس)، `xlsx` (هر شیت → جدول ساختاریافته)، `markdown`.

Chunker ها: `text_chunker` (recursive splitter)، `table_chunker` (حفظ ساختار سطر/ستون)، `image_chunker` (ذخیره در storage + caption اختیاری).

جدا بودن Celery worker از لایه API باعث میشه پردازش سنگین فایل مستقل از HTTP/SSE connection pool اسکیل بشه (مهم برای هم‌زمانی ۱۰۰ کاربر).

---

## 4. knowledge-service

`POST /knowledge-bases/{id}/ingest {file_ids}` → از file-processing-service چانک‌ها رو می‌خونه → Celery batched embedding → upsert در vector DB (Qdrant) با متادیتای kb_id/file_id/chunk_id. `POST /search` توسط `knowledge_retrieval` node در chat-agent-service مصرف میشه. پیشرفت ingestion هم مثل file-service از Redis pub/sub قابل استریم شدنه.

---

## 5. گسترش به Channel Gateway (تلگرام / واتس‌اپ)

هر gateway هیچ منطق چتی نداره، فقط مترجم پروتکله:
1. دریافت webhook از پلتفرم
2. نگاشت پیام به `content_blocks[]` استاندارد (از `shared-schemas`)
3. resolve/create کردن `ChannelIdentity` → `user_id` و `conversation_id` داخلی
4. صدا زدن `chat-agent-service` (`/chat/complete` معمولاً، چون اکثر پلتفرم‌ها token-stream واقعی رو ساپورت نمی‌کنن؛ اگر حس تایپ لازم باشه، استریم داخلی مصرف و batched-edit به پلتفرم فرستاده میشه)
5. ترجمه خروجی (عکس تولیدشده → آپلود به پلتفرم به‌عنوان photo attachment)

**chat-agent-service اصلاً نمی‌فهمه از کدوم کانال اومده** — همین جداسازی باعث میشه اضافه‌کردن گیت‌وی جدید فقط یک سرویس کوچیک جدید باشه، نه تغییر در هسته.

---

## 6. گسترش به Multi-Agent Orchestration

هر Agent از روز اول یک **Callable Unit با قرارداد یکسان** هست:
- `POST /agents/{id}/chat/complete` و `/chat/stream` — از دید یک orchestrator بیرونی، هر Agent چیزی نیست جز یک HTTP endpoint.
- فیلدهای `description`, `capabilities[]`, `is_composable` روی Agent → پایه یک **Agent Registry** (شبیه الگوی agent-card در پروتکل‌هایی مثل A2A).

`multi-agent-orchestrator-service` (سرویس مجزا، مثل یک لایه بالاتر):
- از `chat-agent-service` لیست agentهای composable رو discover می‌کنه.
- یک LangGraph Supervisor داره که هر node ش یک HTTP call به یک Agent هست (نه یک تابع لوکال).
- خودش هم می‌تونه یک `Conversation` با `channel: "orchestrator"` بسازه — یعنی از دید بقیه سیستم دقیقاً مثل یک agent دیگه‌ست، پس قابل تو-در-تو شدنه.

---

## 7. جمع‌بندی: قلاب‌های آماده برای آینده (که از فاز اول لحاظ شدن)

| مورد | چرا از الان |
|---|---|
| `Conversation.channel` + `ChannelIdentity` | جلوگیری از migration پیچیده و تغییر منطق auth موقع اضافه‌شدن گیت‌وی |
| `Agent.description/capabilities/is_composable` | پایه Agent Registry برای multi-agent، هزینه‌ی الان تقریباً صفره |
| قرارداد یکسان `content_blocks[]` (در `shared-schemas`) | چه از تلگرام بیاد چه از orchestrator، فرمت یکیه |
| endpoint استاندارد `/agents/{id}/chat/*` جدا از منطق داخلی گراف | همون چیزیه که فردا orchestrator صدا میزنه |
| `sub_agent_caller` node (اسکلت خالی) در گراف | هوک آماده برای وقتی orchestrator یا حتی خود agent بخواد agent دیگه صدا بزنه |

سرویس‌های `gateways/*` و `multi-agent-orchestrator-service` فقط **scaffold** شدن (ساختار دایرکتوری + یک‌خط توضیح در هر فایل) و پیاده‌سازی نشدن — طبق تصمیم، فعلاً فقط سه سرویس اصلی (chat-agent, file-processing, knowledge) پیاده‌سازی میشن.
