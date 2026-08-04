#!/usr/bin/env python3
"""Validate and synchronize non-chart consumers of versions.yaml."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERSIONS_FILE = "versions.yaml"
GENERATED_CONFIGS = {
    "cluster/versions.generated.tf": (
        ("proxmox", "bpg/proxmox"),
        ("talos", "siderolabs/talos"),
        ("helm", "hashicorp/helm"),
        ("local", "hashicorp/local"),
    ),
    "infrastructure/versions.generated.tf": (
        ("helm", "hashicorp/helm"),
        ("kubernetes", "hashicorp/kubernetes"),
    ),
}


def load_contract() -> dict[str, Any]:
    result = subprocess.run(
        ("yq", "eval", "-o=json", ".", str(ROOT / VERSIONS_FILE)),
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def render_config(
    opentofu_version: str,
    providers: dict[str, Any],
    consumers: tuple[tuple[str, str], ...],
) -> str:
    lines = [
        "# Generated from ../versions.yaml by scripts/check-release-versions.py.",
        "# Do not edit directly; run `task sync-versions`.",
        "",
        "terraform {",
        f'  required_version = ">= {opentofu_version}"',
        "",
        "  required_providers {",
    ]
    for tofu_name, source in consumers:
        lines.extend(
            (
                f"    {tofu_name} = {{",
                f'      source  = "{source}"',
                f'      version = "{providers[tofu_name]}"',
                "    }",
            )
        )
    lines.extend(("  }", "}", ""))
    return "\n".join(lines)


def validate(write: bool) -> int:
    contract = load_contract()
    errors: list[str] = []
    changed: list[str] = []
    opentofu = contract.get("opentofu")
    providers = contract.get("providers")
    platform = contract.get("platform")

    if not isinstance(opentofu, dict) or not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+", str(opentofu.get("version", ""))
    ):
        errors.append(f"{VERSIONS_FILE}: opentofu.version must be X.Y.Z")
    if not isinstance(providers, dict):
        errors.append(f"{VERSIONS_FILE}: providers must be a mapping")
    if not isinstance(platform, dict):
        errors.append(f"{VERSIONS_FILE}: platform must be a mapping")
    if errors:
        return report(errors, changed)

    expected_keys = {
        name for consumers in GENERATED_CONFIGS.values() for name, _ in consumers
    }
    actual_keys = set(providers)
    for key in sorted(expected_keys - actual_keys):
        errors.append(f"{VERSIONS_FILE}: missing provider key {key!r}")
    for key in sorted(actual_keys - expected_keys):
        errors.append(f"{VERSIONS_FILE}: unused provider key {key!r}")
    for key in sorted(expected_keys & actual_keys):
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(providers[key])):
            errors.append(f"{VERSIONS_FILE}: provider {key!r} version must be X.Y.Z")

    if not re.fullmatch(
        r"v[0-9]+\.[0-9]+\.[0-9]+", str(platform.get("talos_linux", ""))
    ):
        errors.append(f"{VERSIONS_FILE}: platform.talos_linux must be vX.Y.Z")
    if not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+", str(platform.get("kubernetes", ""))
    ):
        errors.append(f"{VERSIONS_FILE}: platform.kubernetes must be X.Y.Z")
    if errors:
        return report(errors, changed)

    for relative_path, consumers in GENERATED_CONFIGS.items():
        path = ROOT / relative_path
        expected = render_config(str(opentofu["version"]), providers, consumers)
        actual = path.read_text(encoding="utf-8") if path.exists() else ""
        if actual == expected:
            continue
        if write:
            path.write_text(expected, encoding="utf-8")
            changed.append(relative_path)
        else:
            errors.append(f"{relative_path}: generated provider pins are out of sync")

    workflow_path = ROOT / ".github/workflows/ci.yaml"
    workflow = workflow_path.read_text(encoding="utf-8")
    tofu_pattern = re.compile(r"(?m)^(\s*tofu_version:\s*)[^\s#]+")
    match = tofu_pattern.search(workflow)
    expected_tofu = str(opentofu["version"])
    if match is None:
        errors.append(".github/workflows/ci.yaml: tofu_version was not found")
    elif match.group(0).split(":", 1)[1].strip() != expected_tofu:
        if write:
            workflow_path.write_text(
                tofu_pattern.sub(rf"\g<1>{expected_tofu}", workflow, count=1),
                encoding="utf-8",
            )
            changed.append(".github/workflows/ci.yaml")
        else:
            errors.append(
                f".github/workflows/ci.yaml: tofu_version must be {expected_tofu}"
            )

    cluster_text = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("cluster/talos.tf", "cluster/talos-image.tf")
    )
    if "var.talos_version" in cluster_text or "var.kubernetes_version" in cluster_text:
        errors.append("cluster/: platform versions must come from the root contract")

    return report(errors, changed)


def report(errors: list[str], changed: list[str]) -> int:
    if errors:
        print("[release-versions] validation failed", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print("\nRun `task sync-versions` after updating versions.yaml.", file=sys.stderr)
        return 1
    if changed:
        print("[release-versions] synchronized:")
        for path in sorted(changed):
            print(f"  - {path}")
    else:
        print("[release-versions] passed: all consumers match versions.yaml")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    return validate(parser.parse_args().write)


if __name__ == "__main__":
    raise SystemExit(main())
