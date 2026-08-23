# Bootstrap role: no-deploy (repository validation only).
"""Ensure terraform.tfvars.example documents required OpenTofu inputs."""

from __future__ import annotations

import re
import sys

from homelabctl.project import ROOT

EXAMPLE = ROOT / "terraform.tfvars.example"


VARIABLE = re.compile(r'(?m)^\s*variable\s+"([A-Za-z_][A-Za-z0-9_]*)"\s*\{')
DEFAULT = re.compile(r"(?m)^\s*default\s*=")


def variable_defaults(text: str) -> dict[str, bool]:
    """Return variable names and whether their declaration has a default."""
    matches = list(VARIABLE.finditer(text))
    result: dict[str, bool] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        result[match.group(1)] = DEFAULT.search(text, match.end(), end) is not None
    return result


def required_variables(entrypoint: str) -> set[str]:
    result: dict[str, bool] = {}
    for path in sorted((ROOT / entrypoint).glob("*.tf")):
        result.update(variable_defaults(path.read_text(encoding="utf-8")))
    return {name for name, has_default in result.items() if not has_default}


def main() -> int:
    text = EXAMPLE.read_text(encoding="utf-8")
    errors: list[str] = []

    for variable in sorted(required_variables("cluster")):
        if re.search(rf"(?m)^#?\s*{re.escape(variable)}\s*=", text) is None:
            errors.append(f"cluster input {variable!r} is missing")

    for variable in sorted(required_variables("infrastructure")):
        if f"TF_VAR_{variable}=" not in text:
            errors.append(f"infrastructure input {variable!r} is missing")

    if errors:
        print("[tfvars-example] validation failed", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("[tfvars-example] passed: all required OpenTofu inputs are documented")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
