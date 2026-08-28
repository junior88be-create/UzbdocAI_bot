# Document AI Telegram Bot

A production-oriented Telegram bot that receives PDFs, scanned documents, and photos
(including handwriting), and converts them into structured **DOCX**, **XLSX**, or
**Markdown** files using Google Gemini for OCR / document understanding, while
preserving headings, paragraphs, tables, lists, dates, names, and document numbers as
faithfully as possible. Multiple files can also be processed together as a **batch**,
delivered as one ZIP.

The bot's own interface (menus, buttons, status/error messages) is in **Uzbek
(Cyrillic)** - see `app/bot/handlers/*.py` and `app/bot/keyboards/*.py`. This is UI
text only; the *document content* itself is always preserved in whatever language it
was originally written in (see "Languages" below) - the two are independent. A
`/about` command and "ℹ️ Бот ҳақида" menu button show author/contact information.

## 1. Project description

Pipeline:

```
Telegram → aiogram → validation/storage → local PDF inspection (PyMuPDF)
   → [digital text: send text to Gemini] OR [scanned/handwritten: render pages,
      send images to Gemini Vision, in small batches]
   → structured JSON (validated with Pydantic, cached to disk)
   → DOCX / XLSX / Markdown generators → delivered back via Telegram
```

Key design decisions (see inline docstrings for the full reasoning):

- **Cost control**: digital-text PDFs never trigger a Gemini *Vision* call - only a
  cheap text-structuring call. Only scanned/handwritten pages go through Vision, in
  batches of 4 pages. The validated structured result is cached to disk and reused
  across DOCX/XLSX/MD/re-download requests, and across repeat uploads of identical
  file content (SHA-256 based) by the same user - so asking for DOCX then XLSX never
  calls Gemini twice.
- **Data integrity**: Gemini is instructed (see `app/services/prompts.py`) to never
  invent illegible characters and never "correct" names, dates, document numbers, or
  amounts - uncertain values are flagged (`uncertain: true`) rather than guessed.
- **Ordering integrity**: the structured schema (`app/schemas/extraction.py`) uses a
  single ordered `text_blocks` sequence as the source of truth for reading order,
  with flat `headings`/`paragraphs`/`tables`/`lists` arrays *derived* locally in code
  rather than asked of the model twice - this avoids the model producing two
  divergent representations of the same content.
- **Process separation**: the Celery worker never touches the Telegram Bot API or
  `BOT_TOKEN` - only the bot process does. The worker writes progress to Postgres;
  the bot polls it and edits one Telegram message.
- **Access control fails closed**: an empty `ALLOWED_TELEGRAM_IDS` (and no
  `/adduser`-created database row) means nobody can use the bot, not everybody.

### Batch processing

Tap **📦 Batch process** (main menu) or send `/batch` to process several PDFs/images
together:

1. The bot creates a `Batch` row and enters a short-lived FSM "collecting" state.
2. Send files one at a time (up to `MAX_BATCH_SIZE`, default 10) - each gets a short
   "✅ *filename* added" confirmation, and one persistent status message tracks the
   running count with **Finish** / **Cancel** buttons.
3. Tap **Finish** to pick an output format for the *whole* batch (DOCX / XLSX / MD /
   all three / Automatic), or **Cancel** to discard everything collected so far.
4. Each document is processed through the exact same per-document pipeline as a
   single upload (`app/worker/tasks.py::process_document_task`) - so batching gets
   the same cost-control caching and per-document "Automatic" table-detection logic
   for free. One aggregate progress message shows `✅❌⏳⏳` per document as jobs
   complete.
5. When every document reaches a terminal state, all generated files are bundled
   into a single `batch_results.zip` and delivered as one message, with any failed
   filenames called out in the caption - instead of flooding the chat with
   `documents × formats` separate file messages.

This required no changes to the Celery worker at all (see `app/bot/handlers/batch.py`
docstring) - batching is purely a bot-side grouping/aggregation layer on top of the
existing single-document task.

### Handwritten Uzbek recognition

Uzbek is a primary target language (spec section 5) and its handwriting - in either
script - is where OCR quality matters most, so two things were tuned specifically for
it (see `app/services/prompts.py::_UZBEK_SCRIPT_GUIDANCE` and
`app/services/pdf_service.py`):

- **Script-disambiguation guidance** is always included in the Gemini Vision prompt
  (not only when handwriting is suspected, since a page can silently mix scripts):
  the Uzbek Cyrillic letters that are easy to misread as their more common
  Russian/Cyrillic look-alike in handwriting (Ў vs У, Қ vs К, Ғ vs Г, Ҳ vs Х - the
  distinguishing breve/descender is small and easily smudged), the Uzbek Latin
  apostrophe-letters oʻ/gʻ (explicitly told to preserve whatever glyph the writer
  actually used - straight apostrophe, curly comma, backtick, or omitted - rather
  than "helpfully" normalizing it), and the "sh"/"ch" digraphs.
- **Higher rendering resolution** for pages sent to Vision (260 DPI / 2600px cap, up
  from the MVP's 200 DPI / 2000px) - fine diacritics are the first thing lost at low
  resolution.

Both changes apply to every Vision call, not just ones flagged as handwritten, since
the same script ambiguities affect printed Uzbek text too.

### OCR review step

When Gemini flags any extracted content as uncertain (`uncertain: true` - illegible
handwriting, an ambiguous Cyrillic letter it couldn't confidently resolve, etc.), the
worker stops **before** generating any output file and the bot shows those items
instead of delivering files:

```
🔍 OCR review - 3 item(s) were flagged as uncertain.

1. [Name, p.1] "Ш???ов" (30%)
2. [Date, p.1] "12.03.2024" (55%)
3. [Text, p.2] "o'quvchi ismi noaniq" (40%)

Tap a number to correct it, Continue to proceed as recognized, or Cancel.
```

Tapping a number lets you send the corrected text (or `/skip` to accept it as
recognized); tapping **Continue** re-dispatches processing - the structured
extraction is already cached, so confirming a review **never re-calls Gemini**, it
only (re)generates the requested output file(s). Corrections are written back into
the same cached result, so they also improve future reuse of that exact file content
by the same user (see the cost-control caching above).

This only applies to **single-document** processing (`app/bot/handlers/review.py`).
Batch mode always dispatches with `auto_confirm_review=True` and never pauses for
interactive review - the whole point of batch mode is hands-off bulk processing - but
the final ZIP delivery calls out by filename which documents contained uncertain
content, so nothing is silently swept under the rug.

### Document history & full-text search

**📚 History** / `/history` lists your documents newest-first, 5 at a time, with a
▶️ Show more button once there's another page - each `PROCESSED` entry keeps its
redownload buttons (DOCX/XLSX/MD), and entries are flagged inline if they came
through 📦 batch or contain 🔍 uncertain content.

**🔍 Search** / `/search <text>` finds a past document by filename *or* by its
extracted content - headings, paragraphs, table cells, and entity values (names,
dates, document numbers, amounts, addresses). This uses Postgres's built-in
full-text search (`tsvector` + a GIN index on `Document.search_vector`, a generated
column - see `app/database/models.py::Document`) rather than scanning cached JSON
files at query time or adding a separate search engine dependency, since the app is
already Postgres-backed.

One deliberate choice worth calling out: the index uses the `'simple'` text-search
configuration (tokenize + lowercase, **no stemming**), not `'english'` or
`'russian'`. Content spans Uzbek Latin, Uzbek Cyrillic, Russian, and English -
Postgres ships no Uzbek dictionary, and applying English or Russian stemming rules
to mixed-language text would silently corrupt matches (e.g. stripping a suffix that
happens to look like an English one off an Uzbek word) more than it would help.
`websearch_to_tsquery` is used for the query side, so natural input like
`"exact phrase" -excluded word` works as most users expect from a search box.

Search results show a short snippet of the matched text (built locally in Python
from the stored `search_text`, HTML-escaped for safe display - see
`app/services/search_service.py`) and reuse the same redownload buttons as history.

Consistent with the retention/privacy design: when a document expires
(`cleanup_service.py`), `search_text` is nulled - since `search_vector` is a
generated column derived from it, the document's *content* stops being searchable
automatically (only its filename remains matchable), without any extra cleanup code.

### Voice/audio transcription

Sending a Telegram voice message (🎙), an audio file, **or a phone
recording sent as a plain file attachment** (e.g. a call-recorder app's
`.amr` export, attached via Telegram's generic file picker rather than its
audio/music picker - Telegram reports these as `message.document`, not
`message.audio`, so `voice.py` recognizes them by extension/mime type and
claims them before `document.py`'s PDF/image-only handler would otherwise
reject them) is handled entirely separately from the document pipeline
(`app/bot/handlers/voice.py`): the bot downloads the audio and sends it
directly to Gemini for transcription - no Celery task, no `Document` row,
nothing written to disk, since transcription is a single async I/O-bound
call with no CPU-bound preprocessing step (unlike PDF page rendering).

The transcription prompt (`prompts.build_voice_transcription_prompt`) is
deliberately **not** the document-extraction prompt with different input -
it enforces the opposite instinct on purpose:

- Output follows standard Uzbek (Cyrillic or Latin) or Russian literary
  grammar/spelling, not a verbatim phonetic rendering.
- Noisy/unclear audio is reconstructed from surrounding context into
  coherent text, rather than preserved as-is or flagged uncertain.
- Content that was never actually spoken is still never invented - context
  may only fill in *how* something noisy was likely said, not *what* wasn't
  said at all.
- The audio is transcribed end-to-end and speaker-by-speaker: Gemini returns
  structured segments (`app/schemas/transcript.py::VoiceTranscript`), each
  with a speaker label (their stated name if they say it out loud, otherwise
  a consistent "Спикер 1"/"Спикер 2" - never a guessed real name) and a
  `start_time` (MM:SS from the start of the audio). The prompt explicitly
  forbids stopping after the first speaker or first pause - an earlier
  version of this prompt did exactly that on a real multi-participant call
  recording before this rule was added.

The result is rendered to a `.docx` (`app/services/transcript_docx_service.py`,
entirely in memory - nothing touches disk) with one `[start_time] Speaker`
heading per segment, and sent back as a document, mirroring a real
meeting/call transcript rather than an undifferentiated wall of text. No
speech detected at all comes back as a one-line DOCX saying so.

## 2. Requirements

- Python 3.12+ (developed/tested here on 3.14; both are supported)
- PostgreSQL 14+
- Redis 6+
- A Telegram bot token (via [@BotFather](https://t.me/BotFather))
- A Google Gemini API key
- Docker + Docker Compose (recommended for running the full stack)

## 3. Google Gemini API setup

1. Go to [Google AI Studio](https://aistudio.google.com/) and create an API key.
2. Set `GEMINI_API_KEY` in your `.env`.
3. Set `GEMINI_MODEL` to the model you want to use (e.g. `gemini-3.6-flash`). This is
   **fully configurable via environment variable** - no model name is hard-coded
   anywhere in the code (`app/services/gemini_service.py` always reads
   `settings.gemini_model`).
4. The bot uses [structured output](https://ai.google.dev/gemini-api/docs/structured-output)
   (`response_schema`) so Gemini's JSON is shape-validated by the SDK and then
   re-validated with Pydantic before anything downstream trusts it.

## 4. Telegram BotFather setup

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → follow the prompts.
2. Copy the token into `BOT_TOKEN` in `.env`.
3. Get your own numeric Telegram user ID (e.g. via [@userinfobot](https://t.me/userinfobot))
   and put it in both `ALLOWED_TELEGRAM_IDS` and `ADMIN_TELEGRAM_IDS` so you can use
   and administer the bot immediately.
4. To grant access to anyone else afterwards, you don't need to touch the env var or
   redeploy - message the bot as an admin with `/adduser <their_telegram_id>` (see
   section 9's "Admin commands"). Access is granted if *either* `ALLOWED_TELEGRAM_IDS`
   or a `/adduser`-created database row says so - see `app/bot/middlewares.py`.

## 5. Environment variables

Copy `.env.example` to `.env` and fill in real values. Never commit `.env`.

| Variable | Purpose |
|---|---|
| `BOT_TOKEN` | Telegram bot token |
| `ALLOWED_TELEGRAM_IDS` | Comma-separated allowlist. **Empty = nobody can use the bot until an admin runs `/adduser`** (fail closed). |
| `ADMIN_TELEGRAM_IDS` | Comma-separated subset of the allowlist that gets the ADMIN role |
| `WEBHOOK_URL` / `WEBHOOK_SECRET` / `WEBHOOK_PATH` | Set `WEBHOOK_URL` to switch from long polling to webhook mode |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | Gemini credentials/model - never hard-coded |
| `GEMINI_REQUEST_TIMEOUT_SECONDS` / `GEMINI_MAX_RETRIES` | Resilience tuning |
| `DATABASE_URL` | `postgresql+asyncpg://...` for the app; Alembic swaps in `psycopg2` automatically |
| `REDIS_URL` | Celery broker/result backend |
| `MAX_FILE_SIZE_MB` | Upload size cap (also capped at Telegram Bot API's own 20MB `getFile` limit unless you run a self-hosted Bot API server) |
| `FILE_RETENTION_HOURS` | How long uploaded/generated files live before cleanup deletes them |
| `MAX_PDF_PAGES` | Hard cap on pages per PDF (cost + abuse control) |
| `MAX_BATCH_SIZE` | Max number of files collected into one 📦 batch |
| `MAX_VOICE_DURATION_SECONDS` | Max accepted duration for a 🎙 voice/audio message |
| `LOG_LEVEL` | Standard Python logging level |

## 6. Local installation

```bash
python -m venv .venv
.venv/Scripts/activate   # Windows; use `source .venv/bin/activate` on Linux/macOS
pip install -r requirements.txt
cp .env.example .env     # then edit .env
```

> **Note on `psycopg2-binary`**: it's only used by Alembic's synchronous migration
> driver. If your Python version doesn't have a prebuilt wheel yet, either run
> migrations from a Python 3.12 environment/image, or install PostgreSQL's
> `libpq`/`pg_config` so pip can build it locally. The app itself only needs
> `asyncpg`, which has no such constraint.

You will also need PostgreSQL and Redis running locally (or point `DATABASE_URL` /
`REDIS_URL` at remote instances) - see Docker installation below for the easiest path.

## 7. Docker installation

```bash
docker compose up -d
```

This starts `postgres`, `redis`, runs `migrate` (Alembic, one-shot), then starts
`bot`, `worker`, and `beat` (Celery beat, for hourly cleanup). Storage is a named
volume (`storage_data`) shared between `bot` and `worker`.

## 8. Database migration

```bash
alembic upgrade head
```

The initial migration (`alembic/versions/0001_initial.py`) creates all five tables
(`users`, `documents`, `processing_jobs`, `generated_files`, `audit_logs`) and their
enum types. `alembic/env.py` reads the same `DATABASE_URL` as the app and swaps the
`asyncpg` driver for `psycopg2` since Alembic runs migrations synchronously.

For local development only, `init_models()` (called on bot startup) will also
`CREATE TABLE IF NOT EXISTS` everything via SQLAlchemy metadata - but Alembic is the
source of truth for schema changes going forward.

## 9. Running the bot

Long polling (development):

```bash
python -m app.main
```

Celery worker (required for actual document processing - the bot only enqueues jobs):

```bash
celery -A app.worker.celery_app worker --loglevel=INFO
```

Celery beat (hourly cleanup of expired files):

```bash
celery -A app.worker.celery_app beat --loglevel=INFO
```

Webhook mode (production): set `WEBHOOK_URL` (and ideally `WEBHOOK_SECRET`) in
`.env`; `app/main.py` automatically switches from polling to serving the webhook over
`WEBAPP_HOST:WEBAPP_PORT` + `WEBHOOK_PATH`.

A health endpoint is served on `HEALTH_HOST:HEALTH_PORT` (`/health`, `/health/ready`)
regardless of polling/webhook mode - used by the Docker healthcheck.

### Admin commands

- `/admin` - opens the admin panel (📊 stats, 👥 user list with enable/disable toggles).
- `/adduser <telegram_id>` - grants that Telegram user access immediately, without
  touching `ALLOWED_TELEGRAM_IDS` or redeploying. Creates (or re-activates) their
  `User` row directly; `app/bot/middlewares.py::AccessControlMiddleware` allows a
  user through if *either* the env allowlist or this DB row says so. The user
  supplies their own numeric ID via [@userinfobot](https://t.me/userinfobot) - the
  bot's own unauthorized-access message walks them through this (see
  `app/bot/middlewares.py::_UNAUTHORIZED_MESSAGE_DETAILED`).

Both commands are restricted to `ADMIN_TELEGRAM_IDS`; anyone else gets a plain
"admins only" reply.

## 10. Testing

```bash
pytest
```

86 tests, all offline (no real Gemini/Telegram/Postgres calls - Gemini responses are
exercised via direct schema/retry-logic unit tests, not network mocks of the SDK
itself, since the SDK boundary is thin and the validation/retry logic is what
actually needed coverage). Covered: PDF digital/scanned/mixed detection (PyMuPDF),
DocumentResult schema derivation and validation, Gemini retry/backoff classification,
DOCX/XLSX/Markdown generation fidelity, file-upload security validation (extension,
MIME, magic bytes, size), SHA-256 hashing, storage path-traversal protection, ZIP
bundling for batch delivery, batch progress/status text rendering, prompt content
(Uzbek script guidance present, core anti-fabrication rules present in both prompts),
the OCR review step's item-collection/correction logic, `DocumentResult.to_search_text()`
flattening, and the search-result snippet builder. The full-text query itself
(Postgres `tsvector`/GIN) is not covered here - see "Known limitations" below.

```bash
ruff check app tests   # lint - clean
mypy app                # type check - clean
```

## 11. Production deployment

- Run behind HTTPS (webhook mode requires it - Telegram will not call an `http://`
  webhook URL). Terminate TLS at a reverse proxy (nginx/Caddy/Traefik) in front of
  the `bot` container's `WEBAPP_PORT`.
- Set `WEBHOOK_URL` + `WEBHOOK_SECRET`.
- Scale `worker` horizontally (`celery -A app.worker.celery_app worker --concurrency=N`)
  independently of `bot` - the bot process is lightweight (I/O bound on Telegram +
  Postgres polling), the worker does the CPU/API-bound work.
- Use managed Postgres/Redis in production rather than the docker-compose services.
- Keep `ALLOWED_TELEGRAM_IDS` tightly scoped; add users deliberately.

### Single-container platforms (Railway, Render, Fly.io, etc.)

`docker-compose.yml`'s bot/worker/beat split assumes they share one filesystem (one
Docker volume mounted into all three) for `storage/uploads`, `storage/processed`, and
`storage/outputs`. On a platform where each "service" is its own isolated container
with **no shared volume across services** (Railway's free/hobby tier, notably), the
bot writes an uploaded file the worker can never see, and the worker writes a
generated file the bot can never read back to send to the user - every job fails
with `FileNotFoundError`, with no indication anything is configured wrong until you
check the worker's logs.

`scripts/combined_start.sh` runs all three processes (bot + Celery worker + Celery
beat) in one container instead, so they share one filesystem. To use it, point the
platform's start command at it instead of the Dockerfile's default `CMD`:

```bash
bash scripts/combined_start.sh
```

Then attach **one** persistent volume mounted at `/app/storage` to that single
service (so uploads survive a restart between "received" and "processed"), and set
`DATABASE_URL` / `REDIS_URL` to your managed Postgres/Redis instances - a single
service is enough; you do not need separate worker/beat services on these platforms.
If any of the three processes dies, the script exits (taking the others down with
it) so the platform's restart policy brings all three back up together, rather than
leaving the deployment in a half-alive state where e.g. the bot answers but nothing
ever finishes processing.

## 12. Security recommendations

Already implemented:

- **Allowlist + DB `is_active` flag**, fail-closed by default (empty allowlist = bot
  unusable). Roles: `USER` / `ADMIN`.
- **Upload validation**: extension, declared MIME type, and file magic bytes are all
  cross-checked (`app/utils/security.py`) before anything touches PyMuPDF/Pillow/Gemini.
- **No trusted filenames**: uploaded/generated files get random UUID names on disk;
  the original Telegram filename is only ever used for display and as an export
  filename hint, never as a path component.
- **Path-traversal protection**: every storage path is resolved and checked to stay
  inside `STORAGE_ROOT` (`app/utils/files.py`).
- **No document content in logs**: a logging filter (`app/config/logging.py`)
  redacts anything that looks like a bot token or API key; application code never
  logs extracted text, only metadata (ids, sizes, page counts, error *types*).
- **Retention & cleanup**: `FILE_RETENTION_HOURS` drives automatic deletion of
  uploaded and generated files (`app/services/cleanup_service.py`, run hourly by
  Celery beat). Document rows are soft-expired (kept for `/history` audit purposes)
  rather than hard-deleted, but their file content and cached structured JSON are
  removed from disk.
- **Process isolation**: the Celery worker never receives `BOT_TOKEN` in its runtime
  path - only the bot process talks to Telegram.
- **No stack traces to users**: user-facing error messages are always short and
  friendly; full tracebacks go to server-side logs only (`logger.exception(...)`).

Operational recommendations:

- Run PostgreSQL and Redis with authentication and network isolation (not exposed
  publicly) - the provided `docker-compose.yml` is a development convenience, not a
  hardened production posture (default passwords, no TLS between services).
- Rotate `GEMINI_API_KEY` and `BOT_TOKEN` via your secret manager / Docker secrets in
  production rather than plain `.env` files.
- Review `MAX_FILE_SIZE_MB` / `MAX_PDF_PAGES` for your actual abuse/cost tolerance.

## 13. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Bot doesn't respond at all | Check `BOT_TOKEN`; check the bot process logs for "BOT_TOKEN is not set" |
| "You are not authorized" for everyone including yourself | `ALLOWED_TELEGRAM_IDS` is empty or doesn't include your numeric Telegram ID |
| Uploads are accepted but nothing ever finishes | The Celery `worker` process isn't running, or can't reach `REDIS_URL`/`DATABASE_URL` |
| "File is too large" for files under your configured `MAX_FILE_SIZE_MB` | Telegram's Bot API caps `getFile` downloads at 20MB regardless of your config, unless you run a self-hosted Bot API server |
| Gemini errors / malformed JSON | Check `GEMINI_API_KEY` and `GEMINI_MODEL` are valid; transient errors (timeouts, 429, 5xx) are retried automatically with exponential backoff (`GEMINI_MAX_RETRIES`) |
| `alembic upgrade head` fails to install `psycopg2-binary` | See the note in section 6 - use Python 3.12, or install PostgreSQL dev headers, or build from an image that already has a matching wheel |
| Webhook mode: Telegram never calls the bot | `WEBHOOK_URL` must be a public HTTPS URL; check firewall/reverse-proxy config in front of `WEBAPP_PORT` |

## Architecture reference (file map)

```
app/
  main.py                    entrypoint: aiogram dispatcher + FastAPI health server
  config/settings.py         pydantic-settings config (all env vars, no hard-coded secrets/models)
  config/logging.py          logging setup + secret-redacting filter
  bot/handlers/              start, document upload, voice/audio transcription, batch, review, conversion, history, search, settings, admin
  bot/keyboards/              inline keyboards (main menu, per-document actions, batch, review, admin)
  bot/upload_pipeline.py     shared validate/download/store/inspect logic (single + batch uploads)
  bot/formats.py             shared Telegram-action <-> DB OutputFormat mappings
  bot/states/batch.py        FSM state for batch-upload collection
  bot/states/review.py       FSM state for the OCR review step
  bot/states/search.py       FSM state for the search-query prompt
  bot/middlewares.py         access control (allowlist + is_active) + audit logging
  services/gemini_service.py Gemini client, retries, JSON validation
  services/pdf_service.py    PyMuPDF: digital-vs-scanned inspection, page rendering
  services/ocr_service.py    batched Gemini Vision calls + result merging
  services/document_service.py  top-level orchestration + structured-result caching
  services/review_service.py    OCR review: enumerate/apply corrections to uncertain content
  services/search_service.py    full-text search-result snippet builder (pure logic)
  services/docx_service.py   python-docx generator
  services/excel_service.py  openpyxl generator (one sheet per detected table)
  services/markdown_service.py  Markdown generator
  services/cleanup_service.py   retention-based deletion
  services/prompts.py        all Gemini prompts, centralized (incl. Uzbek script guidance)
  database/                  SQLAlchemy 2.x models, async session, repositories
  schemas/                   Pydantic DTOs, including the Gemini response schema
  utils/                     file safety, hashing, upload validation
  worker/                    Celery app + the document-processing task
```

## Known limitations / what's explicitly out of scope for this MVP

- **Mid-processing cancellation**: the "❌ Cancel" button only cancels before a job
  is dispatched; a running Celery task isn't revoked (it would need `task_id`
  tracking + `celery.control.revoke`). Applies to both single-document and batch
  processing. Low-cost follow-up.
- **Batch and review FSM state are in-memory** (aiogram's default `MemoryStorage`): a
  bot restart mid-collection or mid-review loses that in-progress state (their DB
  rows are unaffected and just get cleaned up passively via normal file retention,
  but the user has to start over - `/batch` again, or re-pick a format to re-trigger
  review). Swapping in `RedisStorage` for FSM state would make both restart-safe;
  not needed for a single-process MVP. Relatedly, only one review session is active
  per user at a time (starting a second one, e.g. by picking a format on a different
  document, replaces it) - acceptable for a single-user-at-a-time bot interaction
  model.
- **Per-user preferences** (default output format, forced language, etc.) aren't
  persisted yet - `/settings` is currently a read-only account/privacy panel.
- **DB-touching tests** (repositories, cleanup service, batch collection/dispatch
  against a real Postgres) are not included in the automated suite - this sandbox
  has no Postgres instance to test against. The repository layer is simple, direct
  SQLAlchemy CRUD; add integration tests against a real/dockerized Postgres as a
  follow-up if desired. The batch feature's pure logic (callback round-tripping,
  progress/status text rendering, ZIP bundling) is unit-tested.
- **JSON export** is implemented in the data model/service layer (`OutputFormat.JSON`
  exists end-to-end) but isn't wired to a dedicated Telegram button yet, per the
  spec's literal per-document button list.
- **Full-text search requires Postgres** (it's built on `tsvector`/GIN, a
  Postgres-specific feature) - this is not a new constraint (the app already
  required Postgres for everything else via `asyncpg`), but it does mean
  `search_vector` uses `Computed(..., persisted=True)`, which SQLAlchemy compiles to
  dialect-specific DDL; `init_models()`'s `create_all()` path has only been verified
  by reading the generated DDL, not against a live database (no Postgres instance in
  this sandbox - see below). `alembic upgrade head` is the source of truth for schema
  changes in any case.
- Search ranks purely by Postgres `ts_rank` (term frequency within the matched
  document) - there's no relevance boosting for filename matches vs. content matches,
  and no fuzzy/typo-tolerant matching (`websearch_to_tsquery` does exact token
  matching after tokenization, not similarity search). Good enough for "find the
  invoice I sent last week"; not a replacement for a dedicated search product.
- Full end-to-end testing against real Telegram/Gemini/Postgres/Redis wasn't possible
  in this environment (no credentials, no Docker available here) - see the final
  implementation summary for exactly what *was* verified.

## Future features (architecture already accommodates these)

AI summarization, document comparison, translation, PDF generation,
digital-signature workflow, a Telegram Mini App, organization-level roles, and an
analytics dashboard. None of these required backfilling the current schema/service
boundaries to add later.

(An OCR review UI, document history, and full-text search are no longer on this
list - they shipped; see "OCR review step" and "Document history & full-text
search" above.)
