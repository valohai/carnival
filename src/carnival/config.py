"""Configuration parsing and validation for Carnival."""

import logging
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

from carnival.envsubst import expand_env, expand_env_if_set, expand_env_int_if_set

logger = logging.getLogger(__name__)


def compact_dict_nones(d: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the dictionary with None values removed."""
    return {k: v for k, v in d.items() if v is not None}


class RestartPolicy(StrEnum):
    """Service restart policies."""

    NO = "no"
    ALWAYS = "always"
    ON_FAILURE = "on-failure"


@dataclass(frozen=True, kw_only=True)
class InitCommand:
    """An initialization command to run sequentially."""

    command: str
    args: list[str] = field(default_factory=list)
    working_dir: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InitCommand":
        """Create InitCommand from TOML dictionary."""
        normalized = _normalize_keys(data)
        command = expand_env(normalized.pop("command"))
        args = [expand_env(arg) for arg in normalized.pop("args", [])]
        working_dir = expand_env_if_set(normalized.pop("working_dir", None))
        if normalized:
            raise ValueError(f"Unknown fields in init command: {sorted(normalized)}")
        return cls(
            command=command,
            args=args,
            working_dir=working_dir,
        )


@dataclass(frozen=True, kw_only=True)
class ServiceConfig:
    """Configuration for a service."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    replicas: int = 1
    restart: RestartPolicy = RestartPolicy.NO
    restart_delay_ms: int = 1000
    restart_limit: int = 0  # 0 = unlimited
    stop_timeout_ms: int = 10_000  # Timeout for graceful shutdown before SIGKILL
    working_dir: str | None = None
    critical: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create ServiceConfig from TOML dictionary with env expansion."""
        normalized = _normalize_keys(data)

        name = expand_env(normalized.pop("name"))
        command = expand_env(normalized.pop("command"))
        args = [expand_env(arg) for arg in normalized.pop("args", [])]

        optionals = compact_dict_nones(
            {
                "replicas": expand_env_int_if_set(normalized.pop("replicas", None)),
                "restart": RestartPolicy(expand_env(normalized.pop("restart", "no"))),
                "restart_delay_ms": expand_env_int_if_set(normalized.pop("restart_delay_ms", None)),
                "restart_limit": expand_env_int_if_set(normalized.pop("restart_limit", None)),
                "stop_timeout_ms": expand_env_int_if_set(normalized.pop("stop_timeout_ms", None)),
                "working_dir": expand_env_if_set(normalized.pop("working_dir", None)),
                "critical": bool(normalized.pop("critical", None)),
            }
        )

        if normalized:
            raise ValueError(f"Unknown fields in service config: {sorted(normalized)}")

        return cls(
            name=name,
            command=command,
            args=args,
            **optionals,
        )


@dataclass(frozen=True, kw_only=True)
class CarnivalConfig:
    """Complete Carnival configuration."""

    init_commands: list[InitCommand] = field(default_factory=list)
    services: list[ServiceConfig] = field(default_factory=list)

    @classmethod
    def from_file(cls, config_path: Path) -> Self:
        """Load configuration from a TOML file."""
        data = tomllib.loads(config_path.read_text())
        cfg = cls.from_dict(data)
        logger.info("Loaded configuration from %s", config_path)
        return cfg

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create CarnivalConfig from parsed TOML dictionary."""
        init_commands = [InitCommand.from_dict(cmd) for cmd in data.get("init", [])]
        services = [ServiceConfig.from_dict(svc) for svc in data.get("service", [])]

        return cls(init_commands=init_commands, services=services)


def _normalize_keys(data: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize kebab-case keys to snake_case.
    """
    return {key.replace("-", "_"): value for key, value in data.items()}
