# Bootstrap role: no-deploy (repository validation only).
"""Ensure terraform.tfvars.example documents every OpenTofu input."""

from __future__ import annotations

import re
import sys

from homelabctl.project import ROOT

EXAMPLE = ROOT / "terraform.tfvars.example"


def declared_variables(entrypoint: str) -> set[str]:
    result: set[str] = set()
    for path in sorted((ROOT / entrypoint).glob("*.tf")):
        result.update(
            re.findall(
                r'(?m)^\s*variable\s+"([A-Za-z_][A-Za-z0-9_]*)"\s*\{',
                path.read_text(encoding="utf-8"),
            )
        )
    return result


def main() -> int:
    text = EXAMPLE.read_text(encoding="utf-8")
    errors: list[str] = []

    for variable in sorted(declared_variables("cluster")):
        if re.search(rf"(?m)^#?\s*{re.escape(variable)}\s*=", text) is None:
            errors.append(f"cluster input {variable!r} is missing")

    for variable in sorted(declared_variables("infrastructure")):
        if f"TF_VAR_{variable}=" not in text:
            errors.append(f"infrastructure input {variable!r} is missing")

    if errors:
        print("[tfvars-example] validation failed", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("[tfvars-example] passed: all OpenTofu inputs are documented")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
