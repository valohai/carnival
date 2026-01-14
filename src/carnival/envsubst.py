import os
import re
from typing import Any

# Pattern to match ${VAR} or ${VAR:-default} or $VAR
ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-((?:[^}\\]|\\.)*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def expand_env(value: Any) -> str:
    """
    Expand environment variables in a string value.

    Supports:
    - ${VAR} - expands to environment variable or empty string
    - ${VAR:-default} - expands to environment variable or default value
    - $VAR - expands to environment variable or empty string

    Args:
        value: The value to expand (can be str, int, or other types)

    Returns:
        The expanded string value
    """
    value = str(value)

    def replacer(match: re.Match) -> str:
        if match.group(3):  # $VAR format
            var_name = match.group(3)
            # If variable not in environment, preserve it for runtime expansion
            return os.environ.get(var_name, match.group(0))
        else:  # ${VAR} or ${VAR:-default} format
            var_name = match.group(1)
            if match.group(2) is not None:
                default_value = match.group(2)
                default_value = default_value.replace("\\}", "}").replace("\\\\", "\\")
                return os.environ.get(var_name, default_value)
            else:
                # No default value - preserve if not in environment
                return os.environ.get(var_name, match.group(0))

    return ENV_VAR_PATTERN.sub(replacer, value)


def expand_env_int_if_set(value: Any) -> int | None:
    return int(expand_env(value)) if value is not None else None


def expand_env_if_set(value: Any) -> str | None:
    return expand_env(value) if value is not None else None
