from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os


def _env_text(name: str, default: str = "") -> str:
    """returns stripped environment text without forcing callers to repeat cleanup."""
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    """parses common deployment boolean strings."""
    value = _env_text(name)
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on", "enabled"}


def _env_float(name: str, default: float) -> float:
    """keeps malformed optional numeric config from breaking startup."""
    value = _env_text(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_list(name: str, default: tuple[str, ...] = ("*",)) -> list[str]:
    """supports comma-separated CORS origins for external frontends."""
    value = _env_text(name)
    if not value:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class AppSettings:
    """centralizes integration switches for plug-and-play deployments."""

    storage_backend: str
    database_url: str
    ui_enabled: bool
    seed_demo_data: bool
    cors_origins: list[str]
    agent_backend: str
    external_agent_url: str
    external_agent_api_key: str
    external_agent_timeout: float

    @property
    def storage_mode(self) -> str:
        """resolves auto storage to postgres when a database URL is supplied."""
        if self.storage_backend == "auto":
            return "postgres" if self.database_url else "memory"
        return self.storage_backend

    def public_dict(self) -> dict[str, object]:
        """exposes non-secret integration config for health and operators."""
        return {
            "storage_backend": self.storage_mode,
            "ui_enabled": self.ui_enabled,
            "seed_demo_data": self.seed_demo_data,
            "cors_origins": self.cors_origins,
            "agent_backend": self.resolved_agent_backend,
            "external_agent_configured": bool(self.external_agent_url),
        }

    @property
    def resolved_agent_backend(self) -> str:
        """keeps the legacy CrewAI flag compatible with the new backend switch."""
        if self.agent_backend != "auto":
            return self.agent_backend
        if self.external_agent_url:
            return "external"
        if _env_bool("SWIFT_CREWAI_ENABLED", False):
            return "crewai"
        return "deterministic"


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    """reads environment once so services share the same integration contract."""
    return AppSettings(
        storage_backend=_env_text("SWIFT_STORAGE_BACKEND", "auto").lower() or "auto",
        database_url=_env_text("DATABASE_URL"),
        ui_enabled=_env_bool("SWIFT_UI_ENABLED", True),
        seed_demo_data=_env_bool("SWIFT_SEED_DEMO_DATA", False),
        cors_origins=_env_list("SWIFT_CORS_ORIGINS"),
        agent_backend=_env_text("SWIFT_AGENT_BACKEND", "auto").lower() or "auto",
        external_agent_url=_env_text("SWIFT_EXTERNAL_AGENT_URL"),
        external_agent_api_key=_env_text("SWIFT_EXTERNAL_AGENT_API_KEY"),
        external_agent_timeout=_env_float("SWIFT_EXTERNAL_AGENT_TIMEOUT", 20.0),
    )


def reset_app_settings() -> None:
    """lets tests update environment-driven settings in-process."""
    get_app_settings.cache_clear()
