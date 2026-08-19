# Bootstrap role: no-deploy (repository validation only).
"""Validate the Argo CD platform orchestration/payload boundary."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from homelabctl.project import ROOT
from homelabctl.yamlutil import load

PLATFORM = ROOT / "argocd/platform"
DOMAINS = (
    "core",
    "identity",
    "delivery",
    "storage",
    "observability",
    "policy",
    "messaging",
)
APPLICATION_DIRS = tuple(PLATFORM / domain / "applications" for domain in DOMAINS)


def load_yaml(path: Path) -> Any:
    return load(path)


def main() -> int:
    issues: list[str] = []
    root_index = load_yaml(PLATFORM / "kustomization.yaml")
    expected_root_resources = [f"{domain}/applications" for domain in DOMAINS]
    if root_index.get("resources") != expected_root_resources:
        issues.append(
            "platform/kustomization.yaml must include only the ordered domain application indexes"
        )

    listed_paths: list[Path] = []
    manifests: list[Path] = []
    for applications in APPLICATION_DIRS:
        app_index = load_yaml(applications / "kustomization.yaml")
        listed_paths.extend(applications / item for item in app_index.get("resources", []))
        manifests.extend(
            path for path in applications.rglob("*.yaml") if path.name != "kustomization.yaml"
        )

    listed_set = set(listed_paths)
    manifests = sorted(manifests)
    manifest_set = set(manifests)

    for path in sorted(listed_set - manifest_set):
        issues.append(f"application index references missing manifest: {path}")
    for path in sorted(manifest_set - listed_set):
        issues.append(f"Application manifest is absent from index: {path}")
    if len(listed_paths) != len(listed_set):
        issues.append("domain application indexes contain duplicate resource paths")

    names: dict[str, Path] = {}
    for path in manifests:
        document = load_yaml(path)
        if document.get("kind") != "Application":
            issues.append(f"non-Application resource found in an applications/: {path}")
            continue

        name = document.get("metadata", {}).get("name")
        if not name:
            issues.append(f"Application has no metadata.name: {path}")
        elif name in names:
            issues.append(f"duplicate Application name {name!r}: {names[name]} and {path}")
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
                issues.append(f"{path}: source path does not exist: {payload_path}")
            if any(
                resolved == applications or applications in resolved.parents
                for applications in APPLICATION_DIRS
            ):
                issues.append(f"{path}: child Application cannot use applications/ as payload")

    for path in sorted(PLATFORM.rglob("*.yaml")):
        if path.name == "kustomization.yaml" or path in manifest_set:
            continue
        document = load_yaml(path)
        if isinstance(document, dict) and document.get("kind") == "Application":
            issues.append(f"Application must live under a platform domain applications/: {path}")

    if issues:
        print("[platform-layout] validation failed", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1

    print(f"[platform-layout] passed: {len(manifests)} Applications indexed exactly once")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
