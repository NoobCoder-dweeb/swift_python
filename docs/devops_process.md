# DevOps And Build Process

This document describes the GitHub CI/CD automation for Project Swift and the
manual steps needed to promote a build into a runtime environment.

## Pipeline Overview

Project Swift uses GitHub Actions:

- CI: `.github/workflows/ci.yml`
- CD: `.github/workflows/cd.yml`

CI validates every pull request and pushes to the main development branches. CD
publishes a Docker image to GitHub Container Registry when a version tag is
pushed or when the workflow is run manually.

## Branch And Release Flow

Use this lightweight flow:

1. Create a feature branch from `main`.
2. Open a pull request.
3. Wait for CI to pass.
4. Merge to `main`.
5. Create a release tag when ready to publish:

```bash
git tag v1.0.0
git push origin v1.0.0
```

The tag triggers CD and publishes a container image to:

```text
ghcr.io/NoobCoder-dweeb/swift_python
```

Manual publishes are also available from the GitHub Actions tab by running the
`CD` workflow and optionally supplying an image tag.

## CI Workflow

CI runs on:

- Pull requests
- Pushes to `main`, `master`, or `develop`

The CI job uses a zero-service configuration:

```dotenv
SWIFT_STORAGE_BACKEND=memory
SWIFT_AGENT_BACKEND=deterministic
SWIFT_CREWAI_ENABLED=0
SWIFT_SEED_DEMO_DATA=0
CREWAI_TRACING_ENABLED=false
CREWAI_TESTING=true
OTEL_SDK_DISABLED=true
```

CI steps:

1. Check out the repository.
2. Install Python 3.13.
3. Install `requirements.txt`.
4. Run Ruff linting:

```bash
ruff check .
```

5. Run tests:

```bash
pytest -p no:rerunfailures tests -q
```

6. Build the Docker image without pushing:

```bash
docker build -t project-swift-app:ci .
```

DeepEval tests are intentionally gated and are not part of normal CI because
they may call local or hosted LLMs. Run them manually using the testing guide:

```text
docs/testing_on_other_machines.md
```

## CD Workflow

CD runs on:

- Tags matching `v*.*.*`
- Manual `workflow_dispatch`

CD steps:

1. Check out the repository.
2. Set up Docker Buildx.
3. Authenticate to GitHub Container Registry using `GITHUB_TOKEN`.
4. Generate Docker tags and labels.
5. Build and push the image.

The workflow publishes immutable SHA tags and release tags. For example:

```text
ghcr.io/NoobCoder-dweeb/swift_python:v1.0.0
ghcr.io/NoobCoder-dweeb/swift_python:sha-abc1234
```

## Runtime Configuration

The image should be deployed with environment variables appropriate to the
target environment. Do not bake secrets into the image.

Minimum zero-service runtime:

```dotenv
SWIFT_STORAGE_BACKEND=memory
SWIFT_AGENT_BACKEND=deterministic
SWIFT_CREWAI_ENABLED=0
SWIFT_SEED_DEMO_DATA=0
SWIFT_SESSION_SECRET_KEY=replace-with-a-long-random-secret
```

Production-like PostgreSQL runtime:

```dotenv
DATABASE_URL=postgresql://user:password@host:5432/swift
SWIFT_STORAGE_BACKEND=postgres
SWIFT_AGENT_BACKEND=deterministic
SWIFT_CREWAI_ENABLED=0
SWIFT_SEED_DEMO_DATA=0
SWIFT_SESSION_SECRET_KEY=replace-with-a-long-random-secret
SWIFT_CORS_ORIGINS=https://your-ui.example.com
```

Optional SMTP runtime:

```dotenv
SWIFT_SMTP_HOST=smtp.gmail.com
SWIFT_SMTP_PORT=587
SWIFT_SMTP_USERNAME=sender@example.com
SWIFT_SMTP_PASSWORD=app-password-or-secret
SWIFT_SMTP_FROM_EMAIL=sender@example.com
SWIFT_SMTP_REPLY_TO_EMAIL=reply-target@example.com
```

Optional CrewAI/Ollama runtime:

```dotenv
SWIFT_AGENT_BACKEND=auto
SWIFT_CREWAI_ENABLED=1
SWIFT_LOCAL_LLM_PROVIDER=ollama
SWIFT_LOCAL_LLM_BASE_URL=http://ollama:11434
SWIFT_SUPERVISOR_LLM_MODEL=nemotron-mini:4b
SWIFT_SALES_LLM_MODEL=llama3.2:3b
SWIFT_DRAFT_LLM_MODEL=qwen2.5:3b
CREWAI_TRACING_ENABLED=false
CREWAI_TESTING=true
OTEL_SDK_DISABLED=true
```

## Build Process

The Docker image is built from `Dockerfile`:

1. Start from `python:3.13-slim`.
2. Install Node.js and npm for Localtunnel support.
3. Install Python dependencies from `requirements.txt`.
4. Copy the application source.
5. Start Uvicorn on port `8000`.

Local build:

```bash
docker build -t project-swift-app:local .
```

Local run with an env file:

```bash
docker run --rm \
  --env-file .env \
  -p 8000:8000 \
  project-swift-app:local
```

Compose build:

```bash
docker compose up --build
```

## Deployment Process

This repository currently publishes a deployable container image. The final
deployment step depends on the hosting platform.

Typical deployment sequence:

1. Pull the release image from GitHub Container Registry.
2. Provide production secrets through the host's secret manager.
3. Run database migrations or seed scripts as needed.
4. Start the container.
5. Check health:

```bash
curl https://your-app.example.com/health
```

For a VM or container host:

```bash
docker pull ghcr.io/NoobCoder-dweeb/swift_python:v1.0.0
docker run -d \
  --name project-swift \
  --env-file /etc/project-swift.env \
  -p 8000:8000 \
  ghcr.io/NoobCoder-dweeb/swift_python:v1.0.0
```

For managed platforms such as Render, Fly.io, ECS, Azure Container Apps, or
Cloud Run, configure the platform to use the published GHCR image and supply the
same runtime environment variables.

## Secrets

Required only when the deployment target needs them:

- `DATABASE_URL`
- `SWIFT_SESSION_SECRET_KEY`
- `SWIFT_SMTP_USERNAME`
- `SWIFT_SMTP_PASSWORD`
- `SWIFT_SMTP_FROM_EMAIL`
- `SWIFT_SMTP_REPLY_TO_EMAIL`
- `SWIFT_EXTERNAL_AGENT_API_KEY`

GitHub Container Registry publishing uses the built-in `GITHUB_TOKEN`; no
additional GitHub secret is needed for the current CD workflow.

## Rollback

Rollback by redeploying a previous image tag:

```bash
docker pull ghcr.io/NoobCoder-dweeb/swift_python:v0.9.0
docker stop project-swift
docker rm project-swift
docker run -d \
  --name project-swift \
  --env-file /etc/project-swift.env \
  -p 8000:8000 \
  ghcr.io/NoobCoder-dweeb/swift_python:v0.9.0
```

If a database migration was applied, check whether rollback also requires a
database restore or forward-fix migration.

## Operational Checks

After deployment:

```bash
curl https://your-app.example.com/health
```

Confirm:

- `storage_backend` matches the intended runtime.
- `agent_backend` matches the intended runtime.
- SMTP is configured only where email delivery should be active.
- Admin-only settings remain protected by role-based access.

## Extending CD

To add automatic deployment after image publishing, add a second job to
`.github/workflows/cd.yml` that depends on `publish-image`.

Common options:

- SSH into a VM and run `docker pull` plus container restart.
- Call a platform deploy hook.
- Update a Kubernetes deployment image.
- Trigger an infrastructure-as-code workflow.

Keep deployment credentials in GitHub Actions secrets and protect production
deployments with GitHub Environments.
