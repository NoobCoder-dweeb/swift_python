# Project Swift

## Local setup

Requirements:

- Python 3.11
- `uv`

Create the virtual environment, install the dependencies, and create the local
environment file:

```bash
uv venv --python 3.11
uv pip install -r requirements.txt --python .venv/bin/python
cp .env.example .env
```

The default environment uses in-memory storage and the deterministic drafting
workflow, so PostgreSQL, SMTP, and a model server are not required.

## Run locally

Start the application:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` and sign in with one of the development accounts:

```text
Sales officer: john / swift123
Sales manager: manager / swift123
Administrator: admin / swift123
```

Stop the application with `Ctrl+C`.

## Run with Docker

Requirements:

- Docker with Docker Compose

Create the Docker environment file and start the application with PostgreSQL:

```bash
cp docker.env.example docker.env
```

Set at least these values in `docker.env`:

```dotenv
POSTGRES_DB=swift
POSTGRES_USER=swift
POSTGRES_PASSWORD=swift
DATABASE_URL=postgresql://swift:swift@postgres:5432/swift
SWIFT_STORAGE_BACKEND=postgres
SWIFT_CREWAI_ENABLED=0
SWIFT_SEED_DEMO_DATA=0
```

Start the services:

```bash
docker compose up --build
```

Open `http://127.0.0.1:8000` and use one of the development accounts listed
above.

Stop the Docker services:

```bash
docker compose down
```
