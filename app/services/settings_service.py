from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from app.crews.agent_config import (
    DEFAULT_AGENT_CONFIG_PATH,
    DEFAULT_TASK_CONFIG_PATH,
    reset_agent_prompt_config_cache,
)
from app.repositories.state_repository import get_state_repository
from app.services.inquiry_guardrails import (
    compile_guardrail_payload,
    default_guardrail_payload,
)


PROMPT_SETTING_KEY = "agent_prompt_overrides"
GUARDRAIL_SETTING_KEY = "guardrail_overrides"
THEME_SETTING_PREFIX = "user_theme:"

PROMPT_GROUPS = {
    "processing": {
        "agent": "sales_processing",
        "task": "extract_inquiry",
        "label": "Sales Processing",
    },
    "drafting": {
        "agent": "email_drafting",
        "task": "draft_response",
        "label": "Email Drafting",
    },
    "supervision": {
        "agent": "supervisor",
        "task": "validation",
        "label": "Supervision & Validation",
    },
}


def get_user_theme(username: str | None) -> str:
    """returns the stored user theme preference, defaulting to light."""
    key = _theme_key(username)
    if not key:
        return "light"
    row = get_state_repository().get_setting(key)
    value = row.get("value") if row else None
    theme = value.get("theme") if isinstance(value, dict) else None
    return theme if theme in {"light", "dark"} else "light"


def save_user_theme(username: str, theme: str) -> dict[str, str]:
    """stores one user's light/dark preference."""
    normalized = (theme or "").strip().lower()
    if normalized not in {"light", "dark"}:
        raise ValueError("Theme must be light or dark.")
    get_state_repository().upsert_setting(
        {
            "key": _theme_key(username),
            "value": {"theme": normalized},
            "updated_at": _timestamp(),
        }
    )
    return {"theme": normalized}


def get_prompt_settings() -> dict[str, Any]:
    """returns defaults plus any persisted prompt overrides for the settings UI."""
    defaults = _default_prompt_payload()
    overrides = _stored_prompt_overrides()
    merged = _merge_prompt_payloads(defaults, overrides)
    return {
        "groups": _ui_groups_from_payload(merged),
        "has_overrides": bool(overrides),
    }


def save_prompt_settings(groups: dict[str, Any]) -> dict[str, Any]:
    """validates and stores editable prompt fields."""
    payload = _prompt_payload_from_groups(groups)
    get_state_repository().upsert_setting(
        {
            "key": PROMPT_SETTING_KEY,
            "value": payload,
            "updated_at": _timestamp(),
        }
    )
    reset_agent_prompt_config_cache()
    return get_prompt_settings()


def reset_prompt_settings() -> dict[str, Any]:
    """removes overrides so YAML files in config/ become authoritative again."""
    get_state_repository().delete_setting(PROMPT_SETTING_KEY)
    reset_agent_prompt_config_cache()
    return get_prompt_settings()


def get_guardrail_settings() -> dict[str, Any]:
    """returns default guardrail regex rules plus any stored overrides."""
    overrides = _stored_guardrail_overrides()
    rules = overrides or default_guardrail_payload()
    return {
        "rules": deepcopy(rules),
        "has_overrides": bool(overrides),
    }


def save_guardrail_settings(rules: Any) -> dict[str, Any]:
    """validates and stores editable guardrail regex rules."""
    compiled = compile_guardrail_payload(_guardrail_payload_from_rules(rules))
    payload = [
        {
            "flag": rule.flag,
            "patterns": [pattern.pattern for pattern in rule.patterns],
        }
        for rule in compiled
    ]
    get_state_repository().upsert_setting(
        {
            "key": GUARDRAIL_SETTING_KEY,
            "value": payload,
            "updated_at": _timestamp(),
        }
    )
    return get_guardrail_settings()


def reset_guardrail_settings() -> dict[str, Any]:
    """removes guardrail overrides so code defaults become authoritative."""
    get_state_repository().delete_setting(GUARDRAIL_SETTING_KEY)
    return get_guardrail_settings()


def _theme_key(username: str | None) -> str:
    normalized = (username or "").strip().lower()
    return f"{THEME_SETTING_PREFIX}{normalized}" if normalized else ""


def _stored_prompt_overrides() -> dict[str, Any]:
    row = get_state_repository().get_setting(PROMPT_SETTING_KEY)
    value = row.get("value") if row else None
    return deepcopy(value) if isinstance(value, dict) else {}


def _stored_guardrail_overrides() -> list[dict[str, Any]]:
    row = get_state_repository().get_setting(GUARDRAIL_SETTING_KEY)
    value = row.get("value") if row else None
    return deepcopy(value) if isinstance(value, list) else []


def _default_prompt_payload() -> dict[str, Any]:
    yaml = _yaml_module()
    agent_root = yaml.safe_load(
        Path(DEFAULT_AGENT_CONFIG_PATH).read_text(encoding="utf-8")
    )
    task_root = yaml.safe_load(
        Path(DEFAULT_TASK_CONFIG_PATH).read_text(encoding="utf-8")
    )
    return {
        "agents": deepcopy(agent_root.get("agents", {})),
        "tasks": deepcopy(task_root.get("tasks", {})),
    }


def _merge_prompt_payloads(
    defaults: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    merged = deepcopy(defaults)
    for section in ("agents", "tasks"):
        section_overrides = overrides.get(section)
        if not isinstance(section_overrides, dict):
            continue
        for key, values in section_overrides.items():
            if key not in merged.get(section, {}) or not isinstance(values, dict):
                continue
            for field_name, value in values.items():
                if isinstance(value, str) and value.strip():
                    merged[section][key][field_name] = value
    return merged


def _ui_groups_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    groups: dict[str, Any] = {}
    agents = payload.get("agents", {})
    tasks = payload.get("tasks", {})
    for group_key, mapping in PROMPT_GROUPS.items():
        agent = agents.get(mapping["agent"], {})
        task = tasks.get(mapping["task"], {})
        groups[group_key] = {
            "label": mapping["label"],
            "agent_key": mapping["agent"],
            "task_key": mapping["task"],
            "role": agent.get("role", ""),
            "goal": agent.get("goal", ""),
            "backstory": agent.get("backstory", ""),
            "task_description": task.get("description", ""),
            "task_expected_output": task.get("expected_output", ""),
        }
    return groups


def _prompt_payload_from_groups(groups: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(groups, dict):
        raise ValueError("Prompt groups must be an object.")

    payload: dict[str, Any] = {"agents": {}, "tasks": {}}
    for group_key, mapping in PROMPT_GROUPS.items():
        group = groups.get(group_key)
        if not isinstance(group, dict):
            raise ValueError(f"Missing prompt group: {group_key}.")

        role = _required_text(group.get("role"), f"{mapping['label']} agent role")
        goal = _required_text(group.get("goal"), f"{mapping['label']} agent goal")
        backstory = _required_text(
            group.get("backstory"),
            f"{mapping['label']} agent backstory",
        )
        description = _required_text(
            group.get("task_description"),
            f"{mapping['label']} task description",
        )
        expected_output = _required_text(
            group.get("task_expected_output"),
            f"{mapping['label']} expected output",
        )
        payload["agents"][mapping["agent"]] = {
            "role": role,
            "goal": goal,
            "backstory": backstory,
        }
        payload["tasks"][mapping["task"]] = {
            "description": description,
            "expected_output": expected_output,
        }
    return payload


def _guardrail_payload_from_rules(rules: Any) -> list[dict[str, Any]]:
    if not isinstance(rules, list):
        raise ValueError("Guardrail rules must be a list.")
    payload: list[dict[str, Any]] = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"Guardrail rule {index + 1} must be an object.")
        flag = _required_text(rule.get("flag"), f"Guardrail rule {index + 1} flag")
        patterns_text = _required_text(
            rule.get("patterns_text"),
            f"Guardrail rule {flag} patterns",
        )
        patterns = [
            line.strip()
            for line in patterns_text.splitlines()
            if line.strip()
        ]
        payload.append({"flag": flag, "patterns": patterns})
    return payload


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required.")
    return value.strip()


def _timestamp() -> str:
    return datetime.now().isoformat()


def _yaml_module() -> Any:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Settings page requires PyYAML to read config defaults.") from exc
    return yaml
