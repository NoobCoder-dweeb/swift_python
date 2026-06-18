# Project Swift Admin Panel

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
SWIFT_PRODUCT_REFERENCE_BASE_URL=https://safetyware.com/?post_type=product&s=
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
