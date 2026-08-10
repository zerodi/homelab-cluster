#!/usr/bin/env python3
# Bootstrap role: no-deploy (repository validation only).
"""Validate the flat docs/ layout and local Markdown links."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = PROJECT_ROOT / "docs"
LINK_PATTERN = re.compile(r"!?\[[^\]]*]\((?P<target>[^)]+)\)")
LEGACY_PATHS = (
    "docs/deployment/",
    "docs/configuration/",
)


def markdown_files() -> list[Path]:
    files = [PROJECT_ROOT / "README.md", PROJECT_ROOT / "AGENTS.md"]
    files.extend(sorted(DOCS_ROOT.rglob("*.md")))
    files.extend(sorted((PROJECT_ROOT / "argocd").rglob("README.md")))
    return [path for path in files if path.is_file()]


def validate_layout() -> list[str]:
    errors: list[str] = []
    for path in sorted(DOCS_ROOT.iterdir()):
        if path.is_dir():
            errors.append(
                f"{path.relative_to(PROJECT_ROOT)}: documentation must use the "
                "flat docs/ layout"
            )
    return errors


def normalized_link_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    target = target.split("#", 1)[0]
    return unquote(target)


def validate_file(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    relative_path = path.relative_to(PROJECT_ROOT)

    for legacy_path in LEGACY_PATHS:
        if legacy_path in text:
            errors.append(f"{relative_path}: stale documentation path {legacy_path}")

    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in LINK_PATTERN.finditer(line):
            target = normalized_link_target(match.group("target"))
            if not target or target.startswith(
                ("http://", "https://", "mailto:", "#")
            ):
                continue
            if target.startswith("/"):
                errors.append(
                    f"{relative_path}:{line_number}: absolute local link {target}"
                )
                continue

            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(PROJECT_ROOT)
            except ValueError:
                errors.append(
                    f"{relative_path}:{line_number}: link leaves repository: "
                    f"{target}"
                )
                continue
            if not resolved.exists():
                errors.append(
                    f"{relative_path}:{line_number}: missing link target {target}"
                )

    return errors


def main() -> int:
    errors = validate_layout()
    for path in markdown_files():
        errors.extend(validate_file(path))

    if errors:
        print("[documentation] validation failed", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(
        "[documentation] passed: layout and local Markdown links are consistent"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
