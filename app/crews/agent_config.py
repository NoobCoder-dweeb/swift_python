from __future__ import annotations

import os
from dataclasses import dataclass
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


def _yaml_module() -> Any:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - depends on environment install
        raise RuntimeError(
            "YAML agent config requires PyYAML. Install requirements.txt before "
            "using CrewAI agent/task configuration."
        ) from exc
    return yaml
