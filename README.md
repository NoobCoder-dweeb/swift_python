# Project Swift Admin Panel

This project reimplements the provided HTML/CSS/JS admin panel as a Python backend application.

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
Ollama-compatible local model endpoint and enable CrewAI:

```bash
export SWIFT_CREWAI_ENABLED=1
export SWIFT_LOCAL_LLM_MODEL="ollama/llama3.2:3b"
export SWIFT_LOCAL_LLM_PROVIDER="ollama"
export SWIFT_LOCAL_LLM_BASE_URL="http://127.0.0.1:11434"
```

Run the stress harness:

```bash
.venv/bin/python -m app.crews.stress_test
.venv/bin/python -m app.crews.stress_test --crewai
```
