from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Any


DEFAULT_AGENT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "agent.yaml"
DEFAULT_TASK_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "tasks.yaml"
AGENT_CONFIG_ENV = "SWIFT_AGENT_CONFIG_PATH"
TASK_CONFIG_ENV = "SWIFT_TASK_CONFIG_PATH"


@dataclass(frozen=True)
class AgentDefinition:
    """CrewAI agent definition loaded from YAML."""

    role: str
    goal: str
    backstory: str
    allow_delegation: bool = False
    max_iter: int = 5
    tools: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TaskPrompt:
    """CrewAI task prompt template loaded from YAML."""

    description: str
    expected_output: str

    def render_description(self, **values: object) -> str:
        rendered_values = {key: str(value) for key, value in values.items()}
        return Template(self.description).safe_substitute(rendered_values)


@dataclass(frozen=True)
class AgentPromptConfig:
    """Container for all YAML-backed CrewAI definitions and prompts."""

    agents: dict[str, AgentDefinition]
    tasks: dict[str, TaskPrompt]


def get_agent_definition(name: str) -> AgentDefinition:
    """Return one configured CrewAI agent definition by key."""
    return load_agent_prompt_config().agents[name]


def get_task_prompt(name: str) -> TaskPrompt:
    """Return one configured CrewAI task prompt by key."""
    return load_agent_prompt_config().tasks[name]


def load_agent_prompt_config(
    path: str | Path | None = None,
    task_path: str | Path | None = None,
) -> AgentPromptConfig:
    """Load CrewAI agent definitions and task prompts from YAML files."""
    config_path = Path(path or os.getenv(AGENT_CONFIG_ENV) or DEFAULT_AGENT_CONFIG_PATH)
    task_config_path = Path(
        task_path or os.getenv(TASK_CONFIG_ENV) or DEFAULT_TASK_CONFIG_PATH
    )
    return _load_agent_prompt_config(
        str(config_path.expanduser()),
        str(task_config_path.expanduser()),
    )


def reset_agent_prompt_config_cache() -> None:
    """clears cached YAML and database prompt settings after settings updates."""
    _load_agent_prompt_config.cache_clear()


@lru_cache(maxsize=4)
def _load_agent_prompt_config(
    config_path: str,
    task_config_path: str,
) -> AgentPromptConfig:
    yaml = _yaml_module()
    agent_root = _load_yaml_mapping(yaml, Path(config_path), "agent config")
    task_root = _load_yaml_mapping(yaml, Path(task_config_path), "task config")
    agent_payloads = _require_mapping(agent_root.get("agents"), "agents")
    task_payloads = _require_mapping(task_root.get("tasks"), "tasks")
    overrides = _stored_prompt_overrides()
    if overrides:
        _merge_prompt_overrides(agent_payloads, task_payloads, overrides)

    agents = {
        key: _agent_definition_from_mapping(key, value)
        for key, value in agent_payloads.items()
    }
    tasks = {
        key: _task_prompt_from_mapping(key, value)
        for key, value in task_payloads.items()
    }
    return AgentPromptConfig(agents=agents, tasks=tasks)


def _load_yaml_mapping(yaml: Any, path: Path, label: str) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _require_mapping(payload, label)


def _agent_definition_from_mapping(key: str, value: Any) -> AgentDefinition:
    payload = _require_mapping(value, f"agents.{key}")
    return AgentDefinition(
        role=_require_text(payload.get("role"), f"agents.{key}.role"),
        goal=_require_text(payload.get("goal"), f"agents.{key}.goal"),
        backstory=_require_text(payload.get("backstory"), f"agents.{key}.backstory"),
        allow_delegation=bool(payload.get("allow_delegation", False)),
        max_iter=int(payload.get("max_iter", 5)),
        tools=_optional_text_list(payload.get("tools", []), f"agents.{key}.tools"),
    )


def _task_prompt_from_mapping(key: str, value: Any) -> TaskPrompt:
    payload = _require_mapping(value, f"tasks.{key}")
    return TaskPrompt(
        description=_require_text(payload.get("description"), f"tasks.{key}.description"),
        expected_output=_require_text(
            payload.get("expected_output"),
            f"tasks.{key}.expected_output",
        ),
    )


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Expected {label} to be a mapping.")
    return value


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Expected {label} to be non-empty text.")
    return value


def _optional_text_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Expected {label} to be a list of text values.")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"Expected {label}[{index}] to be non-empty text.")
        result.append(item)
    return result


def _yaml_module() -> Any:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - depends on environment install
        raise RuntimeError(
            "YAML agent config requires PyYAML. Install requirements.txt before "
            "using CrewAI agent/task configuration."
        ) from exc
    return yaml


def _stored_prompt_overrides() -> dict[str, Any]:
    """loads database prompt overrides without making YAML tests require storage."""
    try:
        from app.services.settings_service import PROMPT_SETTING_KEY
        from app.repositories.state_repository import get_state_repository

        row = get_state_repository().get_setting(PROMPT_SETTING_KEY)
    except Exception:
        return {}
    value = row.get("value") if row else None
    return value if isinstance(value, dict) else {}


def _merge_prompt_overrides(
    agent_payloads: dict[str, Any],
    task_payloads: dict[str, Any],
    overrides: dict[str, Any],
) -> None:
    """applies persisted editable fields on top of YAML defaults."""
    agent_overrides = overrides.get("agents")
    if isinstance(agent_overrides, dict):
        for key, payload in agent_overrides.items():
            if key not in agent_payloads or not isinstance(payload, dict):
                continue
            if not isinstance(agent_payloads[key], dict):
                continue
            for field_name in ("role", "goal", "backstory"):
                value = payload.get(field_name)
                if isinstance(value, str) and value.strip():
                    agent_payloads[key][field_name] = value

    task_overrides = overrides.get("tasks")
    if isinstance(task_overrides, dict):
        for key, payload in task_overrides.items():
            if key not in task_payloads or not isinstance(payload, dict):
                continue
            if not isinstance(task_payloads[key], dict):
                continue
            for field_name in ("description", "expected_output"):
                value = payload.get(field_name)
                if isinstance(value, str) and value.strip():
                    task_payloads[key][field_name] = value
