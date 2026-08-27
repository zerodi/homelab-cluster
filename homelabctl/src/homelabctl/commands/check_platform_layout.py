# Bootstrap role: no-deploy (repository validation only).
"""Validate the Argo CD platform orchestration/payload boundary."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from homelabctl.project import ROOT
from homelabctl.yamlutil import load, load_all

PLATFORM = ROOT / "argocd/platform"
BOOTSTRAP = ROOT / "argocd/bootstrap"
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
    bootstrap_index = load_yaml(BOOTSTRAP / "kustomization.yaml")
    if "projects/default.yaml" not in bootstrap_index.get("resources", []):
        issues.append("bootstrap must manage the default AppProject")
    default_project = load_yaml(BOOTSTRAP / "projects/default.yaml")
    default_spec = default_project.get("spec", {})
    if (
        default_project.get("kind") != "AppProject"
        or default_project.get("metadata", {}).get("name") != "default"
        or default_spec.get("sourceRepos") != []
        or default_spec.get("destinations") != []
        or default_spec.get("clusterResourceWhitelist") != []
        or default_spec.get("namespaceResourceBlacklist") != [{"group": "*", "kind": "*"}]
    ):
        issues.append("default AppProject must be an explicit deny-all fallback")

    root_index = load_yaml(PLATFORM / "kustomization.yaml")
    expected_root_resources = [f"{domain}/applications" for domain in DOMAINS]
    if root_index.get("resources") != expected_root_resources:
        issues.append(
            "platform/kustomization.yaml must include only the ordered domain application indexes"
        )

    observability_api_policies = load_all(
        PLATFORM / "observability/prereqs/kube-apiserver-egress-policy.yaml"
    )
    loki_api_policy = next(
        (
            document
            for document in observability_api_policies
            if isinstance(document, dict)
            and document.get("kind") == "CiliumNetworkPolicy"
            and document.get("metadata", {}).get("name") == "loki-kube-apiserver"
        ),
        {},
    )
    loki_spec = loki_api_policy.get("spec", {})
    if loki_spec.get("endpointSelector", {}).get("matchLabels") != {
        "app.kubernetes.io/instance": "loki",
        "app.kubernetes.io/name": "loki",
    } or loki_spec.get("egress") != [
        {
            "toEntities": ["kube-apiserver"],
            "toPorts": [
                {
                    "ports": [
                        {"port": "443", "protocol": "TCP"},
                        {"port": "6443", "protocol": "TCP"},
                    ]
                }
            ],
        }
    ]:
        issues.append("Loki sidecar must have narrow egress to the Kubernetes API")

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
        if any(
            isinstance(document, dict) and document.get("kind") == "Application"
            for document in load_all(path)
        ):
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
