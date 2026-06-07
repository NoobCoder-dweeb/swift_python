# Project Swift Admin Panel

This project reimplements the provided HTML/CSS/JS admin panel as a Python backend application.

## Docker and PostgreSQL

Audits, drafts, and received emails are stored in PostgreSQL when the app runs
with `SWIFT_STORAGE_BACKEND=postgres` and `DATABASE_URL` set. The web container
does not persist those objects to local files.

Start the app and database together:

```bash
docker compose up --build
```

The API will be available at `http://127.0.0.1:8000`, and PostgreSQL will be
available on localhost port `5432` with the development credentials from
`docker-compose.yml`.

For non-Docker local development, point the app at a PostgreSQL database:

```bash
export DATABASE_URL=postgresql://swift:swift@127.0.0.1:5432/swift
export SWIFT_STORAGE_BACKEND=postgres
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The app expects PostgreSQL in normal runtime. The test suite sets
`SWIFT_STORAGE_BACKEND=memory` so tests do not require a running database.

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

Run the stress harness:

```bash
.venv/bin/python -m app.crews.stress_test
.venv/bin/python -m app.crews.stress_test --crewai
```
