# Project Swift Development And Operations

This project reimplements the provided HTML/CSS/JS admin panel as a Python backend application.

## Plug-and-play integration

Project Swift can run without any external services for first startup:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

With no environment variables, it uses in-memory storage, the deterministic
local drafting workflow, permissive CORS for an external UI, and no demo seed
data. The checked-in `.env.example` follows the same zero-service defaults so
local tests and stress runs are reproducible without PostgreSQL, SMTP, Ollama,
or any hosted agent. External vendors can then plug in the pieces they own:

| External capability | Minimal configuration |
| --- | --- |
| User interface | Use the JSON APIs from any origin, or set `SWIFT_UI_ENABLED=false` for API-only mode. |
| Email server/listener | POST structured JSON, form data, or raw RFC822 email to `/api/emails/ingest`. |
| Email delivery | Set `SWIFT_SMTP_HOST`, `SWIFT_SMTP_USERNAME`, `SWIFT_SMTP_PASSWORD`, and `SWIFT_SMTP_FROM_EMAIL`. |
| PostgreSQL | Set `DATABASE_URL` and optionally `SWIFT_STORAGE_BACKEND=postgres`. |
| Agent service | Set `SWIFT_AGENT_BACKEND=external` and `SWIFT_EXTERNAL_AGENT_URL`. |

Useful integration flags:

```bash
export SWIFT_UI_ENABLED=false
export SWIFT_CORS_ORIGINS=https://ui.example.com
export DATABASE_URL=postgresql://swift:swift@db.example.com:5432/swift
export SWIFT_AGENT_BACKEND=external
export SWIFT_EXTERNAL_AGENT_URL=https://agents.example.com/project-swift/draft
export SWIFT_EXTERNAL_AGENT_API_KEY=replace-me
export SWIFT_SMTP_HOST=smtp.gmail.com
export SWIFT_SMTP_PORT=587
export SWIFT_SMTP_USERNAME=your-sender@gmail.com
export SWIFT_SMTP_PASSWORD=your-gmail-app-password
export SWIFT_SMTP_FROM_EMAIL=your-sender@gmail.com
```

`/health` reports the resolved integration modes without exposing secrets.

When SMTP is configured, approving a draft sends the approved response to the
original sender address on the draft. For example, a draft created from
`shaukoay.dev@gmail.com` is sent back to `shaukoay.dev@gmail.com`; a draft from
another customer address is sent to that address instead. For Gmail SMTP, use a
Google app password rather than your normal account password.

## Docker and PostgreSQL

Audits, drafts, and received emails are stored in PostgreSQL when the app runs
with `SWIFT_STORAGE_BACKEND=postgres` and `DATABASE_URL` set. The web container
does not persist those objects to local files. The bundled Compose file leaves
demo seed data disabled, so pending drafts come from real intake or explicit
API calls rather than startup sample data.

Start the app and database together:

```bash
docker compose up --build
```

The API will be available at `http://127.0.0.1:8000`, and PostgreSQL will be
available on localhost port `5432` with the development credentials from
`docker-compose.yml`.

Inspect PostgreSQL from the running container:

```bash
# List databases.
docker compose exec postgres psql -U swift -d swift -c "\l"

# List public tables.
docker compose exec postgres psql -U swift -d swift -c "\dt public.*"

# Describe one table.
docker compose exec postgres psql -U swift -d swift -c "\d+ swift_products"

# Count records in the main workflow tables.
docker compose exec postgres psql -U swift -d swift -c "SELECT COUNT(*) AS draft_count FROM swift_drafts;"
docker compose exec postgres psql -U swift -d swift -c "SELECT COUNT(*) AS audit_count FROM swift_audits;"
docker compose exec postgres psql -U swift -d swift -c "SELECT COUNT(*) AS email_count FROM swift_emails;"
docker compose exec postgres psql -U swift -d swift -c "SELECT COUNT(*) AS product_count FROM swift_products;"

# Show safety gear product records.
docker compose exec postgres psql -U swift -d swift -c "SELECT product_id, sku, name, category, currency, unit_price, stock_availability, unit_of_measure, status FROM swift_products ORDER BY product_id;"

# Show pending drafts and recent audit entries.
docker compose exec postgres psql -U swift -d swift -c "SELECT draft_id, sender, subject, status, created, updated FROM swift_drafts ORDER BY created DESC;"
docker compose exec postgres psql -U swift -d swift -c "SELECT audit_id, draft_id, action, timestamp FROM swift_audits ORDER BY timestamp DESC NULLS LAST;"
```

If you prefer plain `docker exec`, first find the container name:

```bash
docker ps --filter "name=postgres"
docker exec -it swift_python-postgres-1 psql -U swift -d swift -c "\dt public.*"
docker exec -it swift_python-postgres-1 psql -U swift -d swift -c "SELECT product_id, name, unit_price, stock_availability FROM swift_products ORDER BY product_id;"
```

For non-Docker local development, point the app at a PostgreSQL database:

```bash
export DATABASE_URL=postgresql://swift:swift@127.0.0.1:5432/swift
export SWIFT_STORAGE_BACKEND=postgres
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

If no `DATABASE_URL` is supplied, the app now falls back to in-memory storage for
zero-config startup. Set `SWIFT_STORAGE_BACKEND=postgres` when you want startup
to fail fast unless PostgreSQL is configured.

## Dummy email receiver

Start the local receiver on any open port:

```bash
.venv/bin/python -m app.dummy_email_server --port 8025
```

Send a raw email with curl:

```bash
curl -i http://127.0.0.1:8025/api/emails/ingest \
  -H "Content-Type: message/rfc822" \
  --data-binary $'From: customer@example.com\nTo: sales@example.com\nSubject: Safety helmet stock\n\nDo you have 50 safety helmets in stock?'
```

Or send JSON:

```bash
curl -i http://127.0.0.1:8025/api/emails/ingest \
  -H "Content-Type: application/json" \
  -d '{"from":"customer@example.com","subject":"Product pricing request","body":"Can I get pricing for 40 units of Product X?"}'
```

Incoming email bodies are preprocessed before drafting. The receiver removes
greetings, signatures, quoted replies, disclaimers, contact footers, and other
boilerplate, then keeps the lines most relevant to the customer's pricing or
stock availability query.

## CloudMailin and Localtunnel

For a real Gmail-to-local workflow, CloudMailin should send the incoming message
to the tunnel-facing webhook. The webhook accepts CloudMailin's JSON Normalized
format, requires Basic Auth, creates a pending draft for human review, and sends
the approved reply through the configured Gmail SMTP account when a reviewer
clicks Accept.

Set local credentials in `.env`. For Docker Compose, set the same values in
`docker.env`, because the containers read that file:

```bash
SWIFT_CLOUDMAILIN_BASIC_USERNAME=choose-a-user
SWIFT_CLOUDMAILIN_BASIC_PASSWORD=choose-a-long-password
SWIFT_SMTP_HOST=smtp.gmail.com
SWIFT_SMTP_PORT=587
SWIFT_SMTP_USERNAME=your-sender@gmail.com
SWIFT_SMTP_PASSWORD=your-gmail-app-password
SWIFT_SMTP_FROM_EMAIL=your-sender@gmail.com
SWIFT_SMTP_REPLY_TO_EMAIL=your-cloudmailin-address@cloudmailin.net
SWIFT_PRODUCT_REFERENCE_BASE_URL=https://safetyware.com/products/
```

`SWIFT_SMTP_REPLY_TO_EMAIL` is what makes the real reply loop work: Gmail SMTP
can send the approved response from your Gmail account, while the customer's
Gmail reply is addressed back to CloudMailin and posted into the webhook as a
new inbound email.

Start FastAPI and Localtunnel together:

```bash
.venv/bin/python scripts/run_cloudmailin_localtunnel.py --port 8025
```

Localtunnel runs on Node.js. If `npx` is not available yet, install Node.js
first, or install Localtunnel globally and pass `--localtunnel-bin lt`:

```bash
brew install node
# or, after Node.js is installed:
npm install -g localtunnel
.venv/bin/python scripts/run_cloudmailin_localtunnel.py --port 8025 --localtunnel-bin lt
```

With Docker Compose, the `localtunnel` service starts automatically beside the
app and forwards CloudMailin traffic to the `app:8000` container:

```bash
docker compose up --build
docker compose logs -f localtunnel
```

Use the CloudMailin target URL printed in the `localtunnel` logs.

The script prints the URL to paste into CloudMailin, shaped like:

```text
https://user:password@your-tunnel.loca.lt/api/emails/cloudmailin
```

In CloudMailin, configure the address target to use the JSON Normalized POST
format. Send a real email from Gmail to the CloudMailin address, then open the
local Project Swift UI, review the pending draft, and click Accept to send the
reply through Gmail SMTP.

## Sales processing workflow

The real sales workflow lives under `app/crews`, not in `data.py`. The default
path is deterministic so tests can run without a model server. To run through
CrewAI with a local small language model, start an OpenAI-compatible or
Ollama-compatible local model endpoint. The app loads CrewAI/Ollama settings
from `.env`:

```bash
export DATABASE_URL=postgresql://swift:swift@127.0.0.1:5432/swift
export SWIFT_STORAGE_BACKEND=postgres
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

CrewAI uses a separate small model for each role. The supervisor defaults to
Nemotron Mini, the sales processing/database-context agent defaults to Llama
3.2 3B, and the response drafting agent defaults to Qwen 2.5 3B. The role model
names must remain unique so one model is not reused across the crew.

Run the deterministic stress harness with the same zero-service defaults:

```bash
.venv/bin/python -m app.crews.stress_test
```

Run the CrewAI variant only after a local model endpoint is available:

```bash
.venv/bin/python -m app.crews.stress_test --crewai
```

Generate test results
```bash
.venv/bin/pytest tests/unit
.venv/bin/pytest tests
```

## Agent evaluation with DeepEval

The benchmark goldens live in `data/sales_workflow_goldens.json`. The dataset is
balanced across 15 valid sales cases, 15 incorrect/ambiguous inputs, and 15
adversarial security cases. Security cases must expect a blocked result. Dataset
loading fails if category balance, IDs, metadata, or required fields drift.

Install the optional evaluation dependency:

```bash
uv pip install -r requirements-eval.txt --python .venv/bin/python
```

Run the four-pillar agent benchmark:

```bash
.venv/bin/deepeval test run tests/evaluation/test_sales_agent_deepeval.py
```

For local iteration without DeepEval's post-run trace prompt, run the same file
through pytest:

```bash
.venv/bin/pytest -p no:rerunfailures tests/evaluation/test_sales_agent_deepeval.py -q
```

Useful benchmark flags:

```bash
SWIFT_EVAL_LIMIT=10
SWIFT_EVAL_PRODUCT_SOURCE=database
SWIFT_EVAL_FIELD_F1_THRESHOLD=0.60
SWIFT_EVAL_FAIL_ON_DETERMINISTIC_GATES=1
SWIFT_EVAL_TOOL_THRESHOLD=0.90
SWIFT_EVAL_TASK_THRESHOLD=0.80
SWIFT_EVAL_ENABLE_G_EVAL=0
SWIFT_EVAL_USE_CREWAI=1
```

Put those flags in `.env` for repeatable local runs instead of exporting them
in the shell.

Evaluation runs use the live PostgreSQL `swift_products` table by default. Seed
the database with `init.db` before running the benchmark so the golden dataset is
scored against real persisted catalogue rows, not synthetic facts in the harness.
`SWIFT_EVAL_PRODUCT_SOURCE=golden` is available only for offline harness
development when PostgreSQL is unavailable.

Export CSV tables for results and discussion:

```bash
.venv/bin/python scripts/export_sales_eval_results.py --output-dir reports/evaluation
```

For raw per-case data only:

```bash
.venv/bin/python scripts/export_sales_eval_results.py --output-dir reports/evaluation --raw-only
```

This writes:

| CSV | Purpose |
| --- | --- |
| `sales_eval_case_metrics.csv` | Per-golden raw inputs, expected/actual output JSON, manual processing, SLM/deterministic workflow, and optional LLM/CrewAI metrics, including composite accuracy and token-consumption fields. |
| `sales_eval_aggregate_metrics.csv` | Mean, median, standard deviation, standard error, 95% CI, min, max, and token totals by processing mode. |
| `sales_eval_category_metrics.csv` | The same statistics split into valid, incorrect, and security cohorts so aggregate scores cannot hide weak safety behavior. |
| `sales_eval_pairwise_comparison.csv` | Manual-vs-SLM/LLM deltas for accuracy, tool quality, latency, review time, automation savings, and token consumption. |
| `sales_eval_slm_llm_comparison.csv` | Matched per-case SLM-to-LLM deltas, including response/policy quality, so shared deterministic fields do not dominate the model comparison. |

Add `--include-llm` when the CrewAI/LLM backend is configured:

```bash
.venv/bin/python scripts/export_sales_eval_results.py --include-llm
```

For Gemini API-backed LLM rows, keep `GOOGLE_API_KEY` or `GEMINI_API_KEY`
configured and override the CrewAI provider for the export:

```bash
SWIFT_LOCAL_LLM_PROVIDER=gemini \
SWIFT_LOCAL_LLM_BASE_URL= \
SWIFT_ALLOW_SHARED_LLM_MODELS=1 \
SWIFT_SUPERVISOR_LLM_MODEL=gemini-3.5-flash-lite \
SWIFT_SALES_LLM_MODEL=gemini-3.5-flash-lite \
SWIFT_DRAFT_LLM_MODEL=gemini-3.5-flash-lite \
.venv/bin/python scripts/export_sales_eval_results.py \
  --output-dir reports/evaluation \
  --include-llm \
  --raw-only
```

LLM calls retry up to `SWIFT_LLM_MAX_ATTEMPTS` (default `5`). Empty responses,
provider errors, and validation-triggered regeneration stay on the configured AI
backend. Exhaustion raises an error and aborts the evaluation; an LLM row is never
replaced with deterministic output. Plotting also rejects any contaminated LLM row.
Provider `RetryInfo` delays are honored. For rate-limited benchmarks, set
`SWIFT_EVAL_LLM_CASE_DELAY_SECONDS` to pace cases (for example, `12` for a
15-request/minute account where each case makes roughly three model calls).

If only golden labels change, rescore the saved model outputs without spending
API quota again:

```bash
.venv/bin/python scripts/rescore_sales_eval_results.py
```

The harness is organised around the four pillars of agent evaluation:

| Pillar | What is measured |
| --- | --- |
| Task success | Composite accuracy, field-level precision/recall/F1, response coverage, and explicit policy-compliance scoring for secure blocking, risk flags, and forbidden content; plus DeepEval `GEval` when enabled. |
| Tool quality | DeepEval `ToolCorrectnessMetric`, deterministic tool precision/recall/F1, exact sequence matching, and extracted argument accuracy. |
| Coordination | Supervisor routing precision when CrewAI mode is enabled, duplicate tool-call detection, tool-call count, chokehold count, blocked status, and human-review routing. |
| Cost and performance | Per-case latency, estimated manual/review minutes, automation time saved, input/output/total token consumption, token-count source labels, and aggregate p50/p95-ready CSV statistics. |

Token counts are exact only when the workflow/provider returns usage metadata.
The SLM/deterministic path exposes estimated input/output tokens from the
workflow prompt and final draft text with `token_count_source=estimated_slm_text`.
CrewAI, external, or other LLM paths use provider usage when it is returned;
when local providers do not expose usage metadata, the harness estimates tokens
from prompt/output text and labels them `estimated_crewai_text` or
`estimated_external_text`.

Normal `pytest` runs do not execute this suite. It is intentionally gated by
`SWIFT_RUN_AGENT_EVALS=1` because DeepEval can call an evaluator LLM and may
cost money. To inspect only the deterministic field/tool gates without an LLM
judge, set `SWIFT_EVAL_ALLOW_NO_JUDGE=1`.

If you do not have OpenAI, configure a different DeepEval judge first. For a
free local judge with Ollama:

```bash
ollama run deepseek-r1:1.5b
.venv/bin/deepeval set-ollama --model=deepseek-r1:1.5b
.venv/bin/deepeval test run tests/evaluation/test_sales_agent_deepeval.py
```

For Google's Gemini API free tier:

```bash
.venv/bin/deepeval set-gemini --model=gemini-3.5-flash
.venv/bin/deepeval test run tests/evaluation/test_sales_agent_deepeval.py
```

Gemini's free tier can return temporary `503 UNAVAILABLE` errors when a model is
under high demand. Keep `SWIFT_EVAL_ENABLE_G_EVAL=0` for everyday runs, then
turn it on for a small sample when you specifically need the subjective
LLM-as-judge score:

```bash
SWIFT_EVAL_LIMIT=2
SWIFT_EVAL_ENABLE_G_EVAL=1
```

If Gemini returns `503 UNAVAILABLE`, leave `SWIFT_EVAL_ENABLE_G_EVAL=0` and
rerun. Tool correctness and deterministic field scoring will still complete
without a Gemini call.
