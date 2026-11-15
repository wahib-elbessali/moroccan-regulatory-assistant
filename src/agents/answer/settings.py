"""P4 access to answer settings while the shared config model catches up.

The YAML keys are already part of the shared config contract. The current shared
``AppConfig`` does not expose ``agents`` or ``answer`` yet, so this adapter prefers
typed settings when present and otherwise reads those two sections from config.yaml.
It is deliberately local to P4 and does not change P5's config loader. Reading the
YAML directly also keeps importing the P4 fake independent of application secrets.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config.yaml"


@lru_cache(maxsize=1)
def _yaml_config() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        return {}
    with _CONFIG_PATH.open(encoding="utf-8") as config_file:
        value = yaml.safe_load(config_file) or {}
    return value if isinstance(value, dict) else {}


def setting(section: str, key: str, default: Any) -> Any:
    """Read an answer setting from the shared YAML configuration."""
    yaml_section = _yaml_config().get(section, {})
    if isinstance(yaml_section, dict):
        return yaml_section.get(key, default)
    return default


def app_mode() -> str:
    """Read the top-level application mode without changing the shared config loader."""
    value = _yaml_config().get("mode", "local")
    return value if isinstance(value, str) else "local"
