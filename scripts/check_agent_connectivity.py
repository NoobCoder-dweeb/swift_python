#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_app_settings
from app.crews.agents import MultiAgentLLMConfig


def main() -> int:
    args = _parse_args()
    settings = get_app_settings()
    backend = args.backend or settings.resolved_agent_backend

    print(f"Configured backend: {settings.agent_backend}")
    print(f"Resolved backend: {backend}")

    if backend == "crewai":
        return _check_crewai(args)
    if backend == "external":
        return _check_external_agent(args)
    if backend == "deterministic":
        print("OK deterministic backend selected; no AI agent connection is required.")
        return 0

    print(f"ERROR unsupported backend: {backend}", file=sys.stderr)
    return 2


def _check_crewai(args: argparse.Namespace) -> int:
    try:
        config = MultiAgentLLMConfig.from_env()
    except Exception as exc:
        print(f"ERROR invalid CrewAI LLM config: {exc}", file=sys.stderr)
        return 2

    print("CrewAI role models:")
    for role, role_config in (
        ("supervisor", config.supervisor),
        ("sales_processing", config.sales),
        ("email_drafting", config.drafting),
    ):
        print(
            f"- {role}: provider={role_config.provider}, "
            f"model={role_config.model}, base_url={role_config.base_url or '(provider default)'}"
        )

    providers = {
        config.supervisor.provider,
        config.sales.provider,
        config.drafting.provider,
    }
    if providers == {"ollama"}:
        return _check_ollama(config, args)

    print("Non-Ollama CrewAI provider detected.")
    _print_api_key_status()
    print(
        "OK configuration is present. Run the full workflow to verify provider "
        "authentication and quota."
    )
    return 0


def _check_ollama(config: MultiAgentLLMConfig, args: argparse.Namespace) -> int:
    base_url = config.sales.base_url.rstrip("/")
    print(f"Checking Ollama at {base_url}")

    response = _request_json("GET", f"{base_url}/api/tags", timeout=args.timeout)
    if not response.ok:
        print(f"ERROR Ollama tags request failed: {response.error}", file=sys.stderr)
        return 1

    installed = {
        item.get("name")
        for item in response.data.get("models", [])
        if isinstance(item, dict)
    }
    required = {
        config.supervisor.model,
        config.sales.model,
        config.drafting.model,
    }
    missing = sorted(model for model in required if model not in installed)
    if missing:
        print("ERROR missing Ollama models:", file=sys.stderr)
        for model in missing:
            print(f"- {model}", file=sys.stderr)
        print("Install missing models with: ollama pull <model>", file=sys.stderr)
        return 1

    print("OK Ollama is reachable and all CrewAI role models are installed.")
    if args.probe_generate:
        return _probe_ollama_generate(base_url, config, args.timeout)
    return 0


def _probe_ollama_generate(
    base_url: str,
    config: MultiAgentLLMConfig,
    timeout: float,
) -> int:
    for role, model in config.model_names().items():
        payload = {
            "model": model,
            "prompt": "Reply with exactly: connected",
            "stream": False,
            "options": {"temperature": 0},
        }
        response = _request_json(
            "POST",
            f"{base_url}/api/generate",
            payload=payload,
            timeout=timeout,
        )
        if not response.ok:
            print(f"ERROR {role} model probe failed: {response.error}", file=sys.stderr)
            return 1
        text = str(response.data.get("response", "")).strip()
        print(f"OK {role} generated: {text[:80] or '(empty response)'}")
    return 0


def _check_external_agent(args: argparse.Namespace) -> int:
    settings = get_app_settings()
    if not settings.external_agent_url:
        print("ERROR SWIFT_EXTERNAL_AGENT_URL is not set.", file=sys.stderr)
        return 2

    print(f"Checking external agent API at {settings.external_agent_url}")
    print(
        "API key: "
        + ("configured" if settings.external_agent_api_key else "not configured")
    )

    if not args.probe_generate:
        print("OK external agent URL is configured. Add --probe-generate to POST a sample draft request.")
        return 0

    headers = {"Accept": "application/json"}
    if settings.external_agent_api_key:
        headers["Authorization"] = f"Bearer {settings.external_agent_api_key}"

    response = _request_json(
        "POST",
        settings.external_agent_url,
        payload=_external_probe_payload(),
        headers=headers,
        timeout=args.timeout,
    )
    if not response.ok:
        print(f"ERROR external agent probe failed: {response.error}", file=sys.stderr)
        return 1

    draft = (
        response.data.get("ai_draft")
        or response.data.get("draft")
        or response.data.get("response")
    )
    if not draft:
        print("ERROR external agent responded without draft text.", file=sys.stderr)
        print(json.dumps(response.data, indent=2, sort_keys=True))
        return 1

    print(f"OK external agent returned draft text: {str(draft).strip()[:120]}")
    return 0


def _external_probe_payload() -> dict[str, Any]:
    return {
        "draft_id": "DFT-CONNECTIVITY-CHECK",
        "email": {
            "sender": "connectivity.check@example.com",
            "subject": "Product X price",
            "body": "Can you quote 2 units of Product X?",
        },
        "inquiry": {
            "sender": "connectivity.check@example.com",
            "subject": "Product X price",
            "body": "Can you quote 2 units of Product X?",
            "inquiry_type": "pricing",
            "product_name": "Product X",
            "quantity": 2,
            "requested_delivery": None,
            "missing_information": ["requested_delivery"],
            "risk_flags": [],
            "confidence": 0.9,
        },
        "product_context": {
            "product": "Product X",
            "sku": "PROD-X-001",
            "stock_availability": 500,
            "price": 120.0,
            "currency": "RM",
            "lead_time_days": None,
            "source": "connectivity_check",
            "confidence": 1.0,
            "notes": [],
            "suggested_products": [],
            "listed_products": [],
        },
        "reviewer_feedback": None,
        "previous_draft": None,
        "constraints": {
            "use_only_product_context": True,
            "requires_human_review": True,
        },
    }


def _print_api_key_status() -> None:
    for name in ("OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        print(f"{name}: {'configured' if os.getenv(name) else 'not configured'}")


def _request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> "_HttpResult":
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return _HttpResult(False, {}, f"HTTP {exc.code}: {body[:500]}")
    except URLError as exc:
        return _HttpResult(False, {}, str(exc.reason))
    except TimeoutError:
        return _HttpResult(False, {}, "request timed out")
    except Exception as exc:
        return _HttpResult(False, {}, f"{exc.__class__.__name__}: {exc}")

    try:
        return _HttpResult(True, json.loads(raw or "{}"), "")
    except json.JSONDecodeError:
        return _HttpResult(False, {}, f"response was not JSON: {raw[:500]}")


class _HttpResult:
    def __init__(self, ok: bool, data: dict[str, Any], error: str) -> None:
        self.ok = ok
        self.data = data
        self.error = error


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check whether Project Swift AI agents can reach Ollama or an external API."
    )
    parser.add_argument(
        "--backend",
        choices=("crewai", "external", "deterministic"),
        help="Override SWIFT_AGENT_BACKEND resolution for this check.",
    )
    parser.add_argument(
        "--probe-generate",
        action="store_true",
        help="Send a tiny generation request instead of only checking configuration/model availability.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP timeout in seconds for endpoint checks.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
