#!/usr/bin/env python3
# Bootstrap role: no-deploy (repository validation/generation only).
"""Validate and synchronize container image pins from versions.yaml."""

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
class ImageConsumer:
    key: str
    path: str
    repository: str
    pattern: str
    replacement: str


CONSUMERS = (
    ImageConsumer(
        "echo_server",
        "argocd/apps/echo/resources/deployment.yaml",
        "ealen/echo-server",
        r"(?m)^(\s*image:\s*ealen/echo-server:)[^\s]+(\s*)$",
        r"\g<1>{version}\g<2>",
    ),
    ImageConsumer(
        "garage",
        "argocd/platform/garage/resources/statefulset.yaml",
        "dxflrs/garage",
        r"(?m)^(\s*image:\s*dxflrs/garage:)[^\s]+(\s*)$",
        r"\g<1>{version}\g<2>",
    ),
    ImageConsumer(
        "kubectl",
        "argocd/platform/forgejo/sso/job.yml",
        "bitnami/kubectl",
        r"(?m)^(\s*image:\s*bitnami/kubectl:)[^\s]+(\s*)$",
        r"\g<1>{version}\g<2>",
    ),
    ImageConsumer(
        "stalwart_cli",
        "argocd/platform/stalwart/resources/authentik-oidc-configuration-job.yaml",
        "ghcr.io/stalwartlabs/cli",
        r"(?m)^(\s*image:\s*ghcr.io/stalwartlabs/cli:)[^\s]+(\s*)$",
        r"\g<1>{version}\g<2>",
    ),
    ImageConsumer(
        "stalwart",
        "argocd/platform/stalwart/resources/statefulset.yaml",
        "stalwartlabs/stalwart",
        r"(?m)^(\s*image:\s*stalwartlabs/stalwart:)[^\s]+(\s*)$",
        r"\g<1>{version}\g<2>",
    ),
    ImageConsumer(
        "velero",
        "argocd/platform/velero/values.yaml",
        "docker.io/velero/velero",
        r"(?m)^(\s*tag:\s*)[^\s]+(\s*)$",
        r"\g<1>{version}\g<2>",
    ),
    ImageConsumer(
        "velero_plugin_aws",
        "argocd/platform/velero/values.yaml",
        "docker.io/velero/velero-plugin-for-aws",
        r"(?m)^(\s*image:\s*docker\.io/velero/velero-plugin-for-aws:)[^\s]+(\s*)$",
        r"\g<1>{version}\g<2>",
    ),
    ImageConsumer(
        "test_ssh_git_alpine",
        "test-ssh-git/server/Dockerfile",
        "alpine",
        r"(?m)^(FROM\s+alpine:)[^\s]+(\s*)$",
        r"\g<1>{version}\g<2>",
    ),
)


def load_yaml(path: Path) -> Any:
    result = subprocess.run(
        ("yq", "eval", "-o=json", ".", str(path)),
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def validate(write: bool) -> int:
    contract = load_yaml(PROJECT_ROOT / VERSIONS_FILE)
    versions = contract.get("images")
    errors: list[str] = []
    changed: list[str] = []

    if not isinstance(versions, dict):
        print(f"[image-versions] {VERSIONS_FILE}: images must be a mapping", file=sys.stderr)
        return 1

    expected_keys = {consumer.key for consumer in CONSUMERS}
    actual_keys = set(versions)
    for key in sorted(expected_keys - actual_keys):
        errors.append(f"{VERSIONS_FILE}: missing image key {key!r}")
    for key in sorted(actual_keys - expected_keys):
        errors.append(f"{VERSIONS_FILE}: unused image key {key!r}")

    for consumer in CONSUMERS:
        if consumer.key not in versions:
            continue
        path = PROJECT_ROOT / consumer.path
        text = path.read_text(encoding="utf-8")
        match = re.search(consumer.pattern, text)
        if match is None:
            errors.append(
                f"{consumer.path}: image consumer {consumer.repository!r} was not found"
            )
            continue

        expected = consumer.replacement.format(version=str(versions[consumer.key]))
        replacement = match.expand(expected)
        if match.group(0) == replacement:
            continue
        if write:
            path.write_text(
                text[: match.start()] + replacement + text[match.end() :],
                encoding="utf-8",
            )
            changed.append(consumer.path)
        else:
            errors.append(
                f"{consumer.path}: {consumer.repository!r} does not match "
                f"images.{consumer.key}={versions[consumer.key]!r}"
            )

    if errors:
        print("[image-versions] validation failed", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        if not write:
            print("\nRun `task sync-versions` after updating versions.yaml.", file=sys.stderr)
        return 1

    if changed:
        print("[image-versions] synchronized:")
        for path in sorted(set(changed)):
            print(f"  - {path}")
    else:
        print("[image-versions] passed: all container image pins match versions.yaml")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    return validate(parser.parse_args().write)


if __name__ == "__main__":
    raise SystemExit(main())
