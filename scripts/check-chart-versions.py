#!/usr/bin/env python3
"""Validate and synchronize Helm chart pins from versions.yaml."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERSIONS_FILE = "versions.yaml"


@dataclass(frozen=True)
class TerraformConsumer:
    key: str
    path: str
    chart: str


@dataclass(frozen=True)
class ArgoConsumer:
    key: str
    path: str
    chart: str


TERRAFORM_CONSUMERS = (
    TerraformConsumer("cilium", "bootstrap/talos.tf", "cilium"),
    TerraformConsumer("argo_cd", "infrastructure/argocd.tf", "argo-cd"),
    TerraformConsumer(
        "cert_manager",
        "infrastructure/cert-manager.tf",
        "cert-manager",
    ),
    TerraformConsumer(
        "external_secrets",
        "infrastructure/openbao-eso.tf",
        "external-secrets",
    ),
    TerraformConsumer("openbao", "infrastructure/openbao-eso.tf", "openbao"),
    TerraformConsumer("piraeus", "infrastructure/piraeus.tf", "piraeus"),
    TerraformConsumer(
        "trust_manager",
        "infrastructure/trust-manager.tf",
        "trust-manager",
    ),
)

ARGO_CONSUMERS = (
    ArgoConsumer("authentik", "argocd/platform/authentik.yaml", "authentik"),
    ArgoConsumer(
        "postgresql",
        "argocd/platform/authentik-postgresql.yaml",
        "postgresql",
    ),
    ArgoConsumer("redis", "argocd/platform/authentik-redis.yaml", "redis"),
    ArgoConsumer("forgejo", "argocd/platform/forgejo.yaml", "forgejo"),
    ArgoConsumer(
        "postgresql",
        "argocd/platform/forgejo-postgresql.yaml",
        "postgresql",
    ),
    ArgoConsumer("valkey", "argocd/platform/forgejo-valkey.yaml", "valkey"),
    ArgoConsumer("harbor", "argocd/platform/harbor.yaml", "harbor"),
    ArgoConsumer(
        "postgresql",
        "argocd/platform/harbor-postgresql.yaml",
        "postgresql",
    ),
    ArgoConsumer("valkey", "argocd/platform/harbor-valkey.yaml", "valkey"),
    ArgoConsumer(
        "woodpecker",
        "argocd/platform/woodpecker.yaml",
        "woodpecker",
    ),
    ArgoConsumer("velero", "argocd/platform/velero.yaml", "velero"),
    ArgoConsumer("kyverno", "argocd/platform/kyverno.yaml", "kyverno"),
    ArgoConsumer("grafana", "argocd/platform/grafana.yaml", "grafana"),
    ArgoConsumer(
        "victoria_metrics_single",
        "argocd/platform/victoria-metrics.yaml",
        "victoria-metrics-single",
    ),
    ArgoConsumer("loki", "argocd/platform/loki.yaml", "loki"),
    ArgoConsumer(
        "tempo_distributed",
        "argocd/platform/tempo.yaml",
        "tempo-distributed",
    ),
    ArgoConsumer(
        "opentelemetry_collector",
        "argocd/platform/otel-collector.yaml",
        "opentelemetry-collector",
    ),
    ArgoConsumer("reloader", "argocd/platform/reloader.yaml", "reloader"),
)


def run(*args: str) -> str:
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return result.stdout


def load_yaml(path: Path) -> Any:
    output = run("yq", "eval", "-o=json", ".", str(path))
    return json.loads(output)


def chart_sources(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, dict) or document.get("kind") != "Application":
        return []

    spec = document.get("spec", {})
    sources = spec.get("sources")
    if isinstance(sources, list):
        return [
            source
            for source in sources
            if isinstance(source, dict) and source.get("chart")
        ]

    source = spec.get("source")
    if isinstance(source, dict) and source.get("chart"):
        return [source]
    return []


def discover_argo_consumers(root: Path) -> set[tuple[str, str]]:
    discovered: set[tuple[str, str]] = set()
    paths = sorted(root.glob("argocd/**/*.yaml"))
    paths.extend(sorted(root.glob("argocd/**/*.yml")))
    for path in paths:
        for source in chart_sources(load_yaml(path)):
            discovered.add((str(path.relative_to(root)), str(source["chart"])))
    return discovered


def discover_terraform_consumers(root: Path) -> set[tuple[str, str]]:
    discovered: set[tuple[str, str]] = set()
    for subtree in ("bootstrap", "infrastructure"):
        for path in sorted((root / subtree).glob("*.tf")):
            text = path.read_text(encoding="utf-8")
            for chart in re.findall(r'(?m)^\s*chart\s*=\s*"([^"]+)"\s*$', text):
                discovered.add((str(path.relative_to(root)), chart))
    return discovered


def set_manifest_chart_version(
    path: Path,
    chart: str,
    version: str,
) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    chart_pattern = re.compile(rf"^(\s*)chart:\s*{re.escape(chart)}\s*$")

    for chart_index, raw_line in enumerate(lines):
        line = raw_line.rstrip("\r\n")
        match = chart_pattern.match(line)
        if not match:
            continue

        chart_indent = len(match.group(1))
        for version_index in range(chart_index + 1, len(lines)):
            candidate = lines[version_index].rstrip("\r\n")
            stripped = candidate.lstrip()
            indent = len(candidate) - len(stripped)
            if stripped and indent < chart_indent:
                break
            revision_match = re.match(r"^(\s*)targetRevision:\s*.*$", candidate)
            if revision_match:
                newline = "\n" if lines[version_index].endswith("\n") else ""
                replacement = (
                    f'{revision_match.group(1)}targetRevision: "{version}"{newline}'
                )
                changed = lines[version_index] != replacement
                lines[version_index] = replacement
                if changed:
                    path.write_text("".join(lines), encoding="utf-8")
                return changed

    raise ValueError(f"{path}: chart source {chart!r} was not found")


def validate(root: Path, write: bool) -> int:
    contract = load_yaml(root / VERSIONS_FILE)
    if contract.get("schema_version") != 1:
        print(
            f"[chart-versions] {VERSIONS_FILE}: schema_version must be 1",
            file=sys.stderr,
        )
        return 1

    versions = contract.get("charts")
    if not isinstance(versions, dict):
        print(
            f"[chart-versions] {VERSIONS_FILE}: charts must be a mapping",
            file=sys.stderr,
        )
        return 1

    expected_keys = {
        consumer.key for consumer in (*TERRAFORM_CONSUMERS, *ARGO_CONSUMERS)
    }
    actual_keys = set(versions)
    errors: list[str] = []

    for key in sorted(expected_keys - actual_keys):
        errors.append(f"{VERSIONS_FILE}: missing chart key {key!r}")
    for key in sorted(actual_keys - expected_keys):
        errors.append(f"{VERSIONS_FILE}: unused chart key {key!r}")

    expected_tf = {(item.path, item.chart) for item in TERRAFORM_CONSUMERS}
    actual_tf = discover_terraform_consumers(root)
    for path, chart in sorted(expected_tf - actual_tf):
        errors.append(f"{path}: expected Terraform chart {chart!r} is missing")
    for path, chart in sorted(actual_tf - expected_tf):
        errors.append(
            f"{path}: Terraform chart {chart!r} is not registered in "
            f"{VERSIONS_FILE}"
        )

    for consumer in TERRAFORM_CONSUMERS:
        if consumer.key not in versions:
            continue
        text = (root / consumer.path).read_text(encoding="utf-8")
        expected_expression = (
            rf'(?m)^\s*version\s*=\s*'
            rf'local\.chart_versions\["{re.escape(consumer.key)}"\]\s*$'
        )
        if re.search(expected_expression, text) is None:
            errors.append(
                f"{consumer.path}: chart {consumer.chart!r} must use "
                f'local.chart_versions["{consumer.key}"]'
            )

    expected_argo = {(item.path, item.chart) for item in ARGO_CONSUMERS}
    actual_argo = discover_argo_consumers(root)
    for path, chart in sorted(expected_argo - actual_argo):
        errors.append(f"{path}: expected Argo CD chart {chart!r} is missing")
    for path, chart in sorted(actual_argo - expected_argo):
        errors.append(
            f"{path}: Argo CD chart {chart!r} is not registered in "
            f"{VERSIONS_FILE}"
        )

    changed: list[str] = []
    for consumer in ARGO_CONSUMERS:
        if consumer.key not in versions:
            continue
        path = root / consumer.path
        document = load_yaml(path)
        matching_sources = [
            source
            for source in chart_sources(document)
            if source.get("chart") == consumer.chart
        ]
        if len(matching_sources) != 1:
            errors.append(
                f"{consumer.path}: expected exactly one {consumer.chart!r} source"
            )
            continue

        expected = str(versions[consumer.key])
        actual = str(matching_sources[0].get("targetRevision", ""))
        if actual == expected:
            continue
        if write:
            try:
                if set_manifest_chart_version(
                    path,
                    consumer.chart,
                    expected,
                ):
                    changed.append(consumer.path)
            except ValueError as exc:
                errors.append(str(exc))
        else:
            errors.append(
                f"{consumer.path}: {consumer.chart!r} targetRevision is "
                f"{actual!r}, expected {expected!r}"
            )

    if errors:
        print("[chart-versions] validation failed", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        if not write:
            print(
                "\nRun `task sync-chart-versions` after updating versions.yaml.",
                file=sys.stderr,
            )
        return 1

    if changed:
        print("[chart-versions] synchronized:")
        for path in sorted(changed):
            print(f"  - {path}")
    else:
        print(
            "[chart-versions] passed: all Terraform and Argo CD chart pins "
            "match versions.yaml"
        )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate or synchronize Helm chart pins from versions.yaml.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Update Argo CD targetRevision mirrors in place.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return validate(PROJECT_ROOT, write=args.write)


if __name__ == "__main__":
    raise SystemExit(main())
