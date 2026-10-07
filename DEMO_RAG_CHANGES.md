# تغییرات RAG برای دمو

## قبل از اجرا (الزامی)

1. **`file-processing-service/.env`**
   ```
   MAX_UPLOAD_SIZE_MB=200
   AUTH_DISABLED=true
   VISION_API_KEY=<کلید OpenRouter>
   VISION_BASE_URL=https://openrouter.ai/api/v1
   VISION_MODEL=google/gemini-2.0-flash-001   # باید ورودی تصویر قبول کند؛ در openrouter.ai/models چک کنید
   PDF_OCR_MODE=auto                          # اگر PDF فارسی هنوز شکسته بود: always
   ```
   بدون `VISION_API_KEY` عکس‌ها index نمی‌شوند و PDFها فقط از لایه‌ی متنی خوانده می‌شوند.

2. **`knowledge-service/.env`** و **`chat-agent-service/.env`**: `AUTH_DISABLED=true`

3. **مدل چت:** `gemma-2-27b-it` فقط ۸ هزار توکن context دارد. یا مدل را عوض کنید، یا در
   `chat-agent-service/.env` مقدار `RAG_MAX_CONTEXT_CHARS=5000` بگذارید.

4. **rebuild:**
   ```bash
   docker compose build file-processing-service file-processing-worker knowledge-service knowledge-worker chat-agent-service
   docker compose up -d
   ```

5. **فایل‌ها را دوباره آپلود و ingest کنید** (chunkهای قبلی با کد قدیمی ساخته شده‌اند).
   یک knowledge base جدید بسازید تا vectorهای قدیمی در نتایج نیایند.

## بررسی سریع قبل از دمو

```bash
# بعد از آپلود: chunkها را ببینید (جدول‌ها header دارند؟ عکس‌ها توضیح دارند؟ فارسی سالم است؟)
curl -s http://localhost:8102/api/v1/files/<FILE_ID>/chunks | python3 -m json.tool | head -80

# جستجوی مستقیم
curl -s -X POST http://localhost:8103/api/v1/search -H "Content-Type: application/json" \
  -d '{"kb_ids":["<KB_ID>"],"query":"سوال نمونه","top_k":8}' | python3 -m json.tool

# لاگ RAG در چت
docker compose logs -f chat-agent-service | grep "RAG DEBUG"
```

## چه چیزی درست شد

| بخش | قبل | بعد |
|---|---|---|
| عکس‌ها (Word/Excel/PDF) | `[Embedded image: image1.png]` بی‌معنی embed می‌شد | توضیح vision + متن داخل عکس + داده‌ی نمودار؛ عکس ریز/تکراری حذف |
| Excel | از ردیف ۳۱ به بعد header گم می‌شد | header در همه‌ی chunkها؛ ستون/ردیف خالی حذف؛ `12.0`→`12`، تاریخ خوانا؛ عکس‌های شیت |
| Word | عکس‌ها آخر سند و تکراری؛ سلول ادغام‌شده تکراری | عکس در جای واقعی با زمینه‌ی متنی؛ ستون‌ها هم‌تراز؛ عنوان‌ها با `#` |
| PDF | متن فارسی شکسته؛ صفحه‌ی اسکن‌شده خالی | OCR خودکار صفحات اسکن‌شده/شکسته (جدول‌ها markdown) |
| جدول عریض | ممکن بود از سقف مدل embedding رد شود | سقف کاراکتر + تکرار header |
| ingest مجدد | vectorهای تکراری | idempotent (حذف قبلی + id ثابت) |
| embedding | یک خطای موقت کل فایل را fail می‌کرد | retry + کوتاه‌سازی ورودی طولانی |
| chat | قطعی knowledge-service = خطای ۵۰۰ | ادامه می‌دهد و می‌گوید پیدا نشد |
| prompt | دستور ضعیف انگلیسی | فارسی: فقط از اسناد، جدول دقیق، ذکر منبع، «پیدا نشد» به‌جای حدس |
| سؤال پیگیری | «قیمتش چنده؟» خام جستجو می‌شد | بازنویسی به سؤال کامل قبل از جستجو |
| آپلود | ۱۰۰ مگ | ۲۰۰ مگ (timeoutهای proxy هم بیشتر شد) |
| احراز هویت | الزامی | اختیاری با `AUTH_DISABLED` (توکن معتبر اگر باشد هنوز استفاده می‌شود) |

## محدودیت‌ها
- `.doc` و `.xls` (فرمت قدیمی) پشتیبانی نمی‌شوند؛ به docx/xlsx تبدیل کنید.
- پشت nginx: `client_max_body_size 200M;`
- با `AUTH_DISABLED` همه‌ی درخواست‌های بدون توکن متعلق به `local-user` هستند؛ داده‌هایی که قبلاً با
  کاربر دیگری (مثلاً `demo-user`) ساخته شده‌اند در لیست‌ها دیده نمی‌شوند مگر با توکن همان کاربر.
- برای برگرداندن احراز هویت: `AUTH_DISABLED=false` در هر سه سرویس.
