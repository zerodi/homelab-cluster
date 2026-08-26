from __future__ import annotations

import copy
import io
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


def load(path: Path, *, round_trip: bool = False) -> Any:
    yaml = YAML() if round_trip else YAML(typ="safe")
    return yaml.load(path)


def load_all(path: Path) -> list[Any]:
    return list(YAML(typ="safe").load_all(path))


def loads(value: str) -> Any:
    return YAML(typ="safe").load(value)


def dump(data: Any) -> str:
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    yaml.width = 4096
    stream = io.StringIO()
    yaml.dump(data, stream)
    return stream.getvalue()


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        result = copy.deepcopy(base)
        for key, value in override.items():
            result[key] = deep_merge(result[key], value) if key in result else copy.deepcopy(value)
        return result
    return copy.deepcopy(override)


def get_path(data: Any, dotted: str, default: Any = "") -> Any:
    current = data
    for part in dotted.strip(".").split("."):
        if not part:
            continue
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current
