# Testing On Other Machines

This guide is for reproducing Project Swift tests and evaluation reports on a
different laptop or workstation. Prefer env files over one-off terminal exports
so the run can be repeated exactly.

## 1. Prepare The Machine

Install the normal and evaluation dependencies:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r requirements-eval.txt
```

For CrewAI/LLM runs, install Ollama and pull the three local SLMs:

```bash
ollama pull nemotron-mini:4b
ollama pull llama3.2:3b
ollama pull qwen2.5:3b
ollama list
```

Make sure Ollama is running and reachable at `http://127.0.0.1:11434`.

## 2. Use A Testing Env File

The application automatically loads `.env`. For a separate test configuration,
create `.env.testing` and run commands through `python-dotenv`:

```bash
.venv/bin/python -m dotenv -f .env.testing run -- <command>
```

Alternatively, on a disposable test checkout, copy the testing file into the
default location:

```bash
cp .env.testing .env
```

Do not commit real `.env` files with passwords or API keys.

## 3. Deterministic Test Env

Use this when the other machine does not have PostgreSQL, SMTP, or Ollama.

Create `.env.testing`:

```dotenv
DATABASE_URL=
SWIFT_STORAGE_BACKEND=memory
SWIFT_AGENT_BACKEND=deterministic
SWIFT_CREWAI_ENABLED=0
SWIFT_SEED_DEMO_DATA=0
CREWAI_TRACING_ENABLED=false
CREWAI_TESTING=true
OTEL_SDK_DISABLED=true
```

Run unit tests:

```bash
.venv/bin/python -m dotenv -f .env.testing run -- \
  .venv/bin/pytest -p no:rerunfailures tests/unit -q
```

Run all non-gated tests:

```bash
.venv/bin/python -m dotenv -f .env.testing run -- \
  .venv/bin/pytest -p no:rerunfailures tests -q
```

## 4. Full CrewAI/Ollama Evaluation Env

Use this when the other machine has Ollama and the three local SLMs installed.

Create `.env.testing`:

```dotenv
DATABASE_URL=
SWIFT_STORAGE_BACKEND=memory
SWIFT_AGENT_BACKEND=auto
SWIFT_CREWAI_ENABLED=1
SWIFT_LOCAL_LLM_PROVIDER=ollama
SWIFT_LOCAL_LLM_BASE_URL=http://127.0.0.1:11434
SWIFT_SUPERVISOR_LLM_MODEL=nemotron-mini:4b
SWIFT_SALES_LLM_MODEL=llama3.2:3b
SWIFT_DRAFT_LLM_MODEL=qwen2.5:3b
SWIFT_CREWAI_HOME=/tmp/project_swift_crewai_home
CREWAI_TRACING_ENABLED=false
CREWAI_TESTING=true
OTEL_SDK_DISABLED=true

SWIFT_RUN_AGENT_EVALS=1
SWIFT_EVAL_LIMIT=0
SWIFT_EVAL_USE_CREWAI=1
SWIFT_EVAL_ALLOW_NO_JUDGE=1
SWIFT_EVAL_ENABLE_G_EVAL=0
SWIFT_EVAL_FIELD_F1_THRESHOLD=0.60
SWIFT_EVAL_TOOL_THRESHOLD=0.90
SWIFT_EVAL_TASK_THRESHOLD=0.80
```

Run the full DeepEval golden suite:

```bash
.venv/bin/python -m dotenv -f .env.testing run -- \
  .venv/bin/deepeval test run tests/evaluation/test_sales_agent_deepeval.py
```

Export full manual, SLM, and LLM metrics:

```bash
.venv/bin/python -m dotenv -f .env.testing run -- \
  .venv/bin/python scripts/export_sales_eval_results.py \
  --output-dir reports/evaluation \
  --include-llm
```

Regenerate plots and the discussion summary:

```bash
.venv/bin/python -m dotenv -f .env.testing run -- \
  .venv/bin/python scripts/plot_sales_eval_results.py \
  --input reports/evaluation/sales_eval_case_metrics.csv \
  --output-dir reports/evaluation/figures
```

Expected full-dataset shape:

- `reports/evaluation/sales_eval_case_metrics.csv` should have `150` rows.
- Processing modes should be `manual=50`, `slm=50`, and `llm=50`.
- Figure 2, `reports/evaluation/figures/figure_2_slm_accuracy_by_module.svg`,
  should be based on more than one inquiry module. The current full golden file
  has 17 modules.

Quick validation:

```bash
.venv/bin/python - <<'PY'
import csv
from collections import Counter

rows = list(csv.DictReader(open("reports/evaluation/sales_eval_case_metrics.csv", newline="", encoding="utf-8")))
slm_rows = [row for row in rows if row["processing_mode"] == "slm"]
print("total rows:", len(rows))
print("modes:", dict(Counter(row["processing_mode"] for row in rows)))
print("SLM modules:", len(Counter(row["module"] for row in slm_rows)))
print(dict(Counter(row["module"] for row in slm_rows)))
PY
```

## 5. PostgreSQL-Backed Evaluation Env

Use this when the other machine should score against a live product database.

Create `.env.testing.postgres`:

```dotenv
DATABASE_URL=postgresql://swift:swift@127.0.0.1:5432/swift
SWIFT_STORAGE_BACKEND=postgres
SWIFT_AGENT_BACKEND=auto
SWIFT_CREWAI_ENABLED=1
SWIFT_LOCAL_LLM_PROVIDER=ollama
SWIFT_LOCAL_LLM_BASE_URL=http://127.0.0.1:11434
SWIFT_SUPERVISOR_LLM_MODEL=nemotron-mini:4b
SWIFT_SALES_LLM_MODEL=llama3.2:3b
SWIFT_DRAFT_LLM_MODEL=qwen2.5:3b
CREWAI_TRACING_ENABLED=false
CREWAI_TESTING=true
OTEL_SDK_DISABLED=true
SWIFT_RUN_AGENT_EVALS=1
SWIFT_EVAL_LIMIT=0
SWIFT_EVAL_USE_CREWAI=1
SWIFT_EVAL_ALLOW_NO_JUDGE=1
```

Start PostgreSQL and seed the product table before running evaluation:

```bash
docker compose up -d postgres
docker compose exec postgres psql -U swift -d swift -f /docker-entrypoint-initdb.d/001-init.sql
```

Then run the same DeepEval, export, and plot commands with
`.env.testing.postgres`.

## 6. Troubleshooting

- If only 2 cases run, check `SWIFT_EVAL_LIMIT`. Full evaluation needs
  `SWIFT_EVAL_LIMIT=0`.
- If LLM rows show `execution_mode=deterministic`, the CrewAI/Ollama path fell
  back. Check that Ollama is running and the three models are installed.
- If `routing_precision` is blank for LLM rows, that row did not complete in
  CrewAI mode.
- If DeepEval fails but export succeeds, use the CSV and figures for analysis;
  DeepEval failures usually identify modules where expected tool trajectories
  or response terms diverged.
