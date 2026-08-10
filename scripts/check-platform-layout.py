#!/usr/bin/env python3
# Bootstrap role: no-deploy (repository validation only).
"""Validate the Argo CD platform orchestration/payload boundary."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "argocd/platform"
APPLICATIONS = PLATFORM / "applications"


def load_yaml(path: Path) -> Any:
    result = subprocess.run(
        ["yq", "eval", "-o=json", ".", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def main() -> int:
    issues: list[str] = []
    root_index = load_yaml(PLATFORM / "kustomization.yaml")
    if root_index.get("resources") != ["applications"]:
        issues.append(
            "platform/kustomization.yaml must include only the applications index"
        )

    app_index = load_yaml(APPLICATIONS / "kustomization.yaml")
    listed_paths = [APPLICATIONS / item for item in app_index.get("resources", [])]
    listed_set = set(listed_paths)
    manifests = sorted(
        path
        for path in APPLICATIONS.rglob("*.yaml")
        if path.name != "kustomization.yaml"
    )
    manifest_set = set(manifests)

    for path in sorted(listed_set - manifest_set):
        issues.append(f"application index references missing manifest: {path}")
    for path in sorted(manifest_set - listed_set):
        issues.append(f"Application manifest is absent from index: {path}")
    if len(listed_paths) != len(listed_set):
        issues.append("application index contains duplicate resource paths")

    names: dict[str, Path] = {}
    for path in manifests:
        document = load_yaml(path)
        if document.get("kind") != "Application":
            issues.append(f"non-Application resource found in applications/: {path}")
            continue

        name = document.get("metadata", {}).get("name")
        if not name:
            issues.append(f"Application has no metadata.name: {path}")
        elif name in names:
            issues.append(
                f"duplicate Application name {name!r}: {names[name]} and {path}"
            )
        else:
            names[name] = path

        spec = document.get("spec", {})
        sources = spec.get("sources", [])
        if isinstance(spec.get("source"), dict):
            sources = [spec["source"], *sources]
        for source in sources:
            payload_path = source.get("path") if isinstance(source, dict) else None
            if not payload_path or not payload_path.startswith("platform/"):
                continue
            resolved = ROOT / "argocd" / payload_path
            if not resolved.is_dir():
                issues.append(
                    f"{path}: source path does not exist: {payload_path}"
                )
            if resolved == APPLICATIONS or APPLICATIONS in resolved.parents:
                issues.append(
                    f"{path}: child Application cannot use applications/ as payload"
                )

    for path in sorted(PLATFORM.rglob("*.yaml")):
        if path == APPLICATIONS / "kustomization.yaml" or path in manifest_set:
            continue
        document = load_yaml(path)
        if isinstance(document, dict) and document.get("kind") == "Application":
            issues.append(f"Application must live under platform/applications: {path}")

    if issues:
        print("[platform-layout] validation failed", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1

    print(
        f"[platform-layout] passed: {len(manifests)} Applications indexed exactly once"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
