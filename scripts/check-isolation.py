#!/usr/bin/env python3
"""Enforce the repository ownership boundary around bootstrap/."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BOOTSTRAP_DIR = PROJECT_ROOT / "bootstrap"
DEFAULT_TFVARS_FILES = (
    PROJECT_ROOT / "terraform.tfvars.example",
    PROJECT_ROOT / "secrets.sops.tfvars.example",
)


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    message: str


FORBIDDEN_NAME_PARTS = {
    "argocd",
    "authentik",
    "cert_manager",
    "echo",
    "external_secret",
    "external_secrets",
    "forgejo",
    "garage",
    "grafana",
    "harbor",
    "kyverno",
    "linstor",
    "loki",
    "openbao",
    "piraeus",
    "platform",
    "runtime",
    "tempo",
    "trust_manager",
    "velero",
    "victoria_metrics",
    "woodpecker",
}

FORBIDDEN_SOURCE_PATTERNS = (
    (
        re.compile(r'(?m)^\s*provider\s+"kubernetes"\s*\{'),
        "bootstrap must not configure the Kubernetes provider",
    ),
    (
        re.compile(r'(?m)^\s*(?:resource|data)\s+"kubernetes_[^"]+"\s+"'),
        "bootstrap must not own Kubernetes provider resources",
    ),
    (
        re.compile(r'(?m)^\s*resource\s+"helm_release"\s+"'),
        "bootstrap may render Cilium but must not own Helm releases",
    ),
    (
        re.compile(r'(?m)^\s*source\s*=\s*"hashicorp/kubernetes"\s*$'),
        "bootstrap must not depend on the Kubernetes provider",
    ),
    (
        re.compile(r'(?i)(?:^|["/])\.\./(?:argocd|infrastructure)(?:[/"]|$)'),
        "bootstrap must not read files from argocd/ or infrastructure/",
    ),
    (
        re.compile(
            r'(?i)apiVersion\s*[:=]\s*"?'
            r'(?:argoproj\.io|cert-manager\.io|external-secrets\.io|'
            r'piraeus\.io|trust\.cert-manager\.io)/'
        ),
        "bootstrap must not declare platform/runtime Kubernetes API objects",
    ),
    (
        re.compile(
            r'(?i)kind\s*[:=]\s*"?'
            r'(?:Application|AppProject|Bundle|Certificate|ClusterIssuer|'
            r'ClusterSecretStore|ExternalSecret|LinstorCluster|'
            r'LinstorSatelliteConfiguration|StorageClass)\b'
        ),
        "bootstrap must not declare platform/runtime Kubernetes kinds",
    ),
    (
        re.compile(r'(?i)(?:secret/data/)?platform/[a-z0-9_./-]+'),
        "bootstrap must not reference runtime secret paths",
    ),
)


def strip_line_comment(line: str) -> str:
    """Remove HCL line comments while preserving quoted strings."""

    in_string = False
    escaped = False
    index = 0

    while index < len(line):
        char = line[index]

        if escaped:
            escaped = False
        elif char == "\\" and in_string:
            escaped = True
        elif char == '"':
            in_string = not in_string
        elif not in_string and char == "#":
            return line[:index]
        elif (
            not in_string
            and char == "/"
            and index + 1 < len(line)
            and line[index + 1] == "/"
        ):
            return line[:index]

        index += 1

    return line


def active_hcl(text: str) -> str:
    return "\n".join(strip_line_comment(line) for line in text.splitlines())


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def name_crosses_boundary(name: str) -> bool:
    normalized = name.lower().replace("-", "_")
    return any(part in normalized for part in FORBIDDEN_NAME_PARTS)


def scan_terraform_file(path: Path, display_root: Path) -> list[Violation]:
    raw_text = path.read_text(encoding="utf-8")
    text = active_hcl(raw_text)
    violations: list[Violation] = []
    display_path = path.relative_to(display_root)

    for pattern, message in FORBIDDEN_SOURCE_PATTERNS:
        for match in pattern.finditer(text):
            violations.append(
                Violation(display_path, line_number(text, match.start()), message)
            )

    for match in re.finditer(
        r'(?m)^\s*(variable|output)\s+"([^"]+)"\s*\{', text
    ):
        block_type, name = match.groups()
        if name_crosses_boundary(name):
            violations.append(
                Violation(
                    display_path,
                    line_number(text, match.start()),
                    f'bootstrap {block_type} "{name}" belongs to platform/runtime',
                )
            )

    return violations


def declared_bootstrap_variables(bootstrap_dir: Path) -> set[str]:
    declared: set[str] = set()
    for path in sorted(bootstrap_dir.glob("*.tf")):
        text = active_hcl(path.read_text(encoding="utf-8"))
        declared.update(
            match.group(1)
            for match in re.finditer(r'(?m)^\s*variable\s+"([^"]+)"\s*\{', text)
        )
    return declared


def nesting_delta(line: str) -> int:
    """Count HCL collection delimiters outside quoted strings."""

    delta = 0
    in_string = False
    escaped = False

    for char in line:
        if escaped:
            escaped = False
        elif char == "\\" and in_string:
            escaped = True
        elif char == '"':
            in_string = not in_string
        elif not in_string and char in "{[(":
            delta += 1
        elif not in_string and char in "}])":
            delta -= 1

    return delta


def top_level_tfvars_assignments(text: str) -> Iterable[tuple[str, int]]:
    depth = 0

    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = strip_line_comment(raw_line)
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if depth == 0 and match:
            yield match.group(1), number
        depth += nesting_delta(line)


def scan_tfvars_file(
    path: Path, declared_variables: set[str], display_root: Path
) -> list[Violation]:
    if not path.exists():
        return []

    violations: list[Violation] = []
    display_path = path.relative_to(display_root)
    text = path.read_text(encoding="utf-8")

    for name, number in top_level_tfvars_assignments(text):
        if name not in declared_variables:
            violations.append(
                Violation(
                    display_path,
                    number,
                    f'top-level input "{name}" is not declared by bootstrap/',
                )
            )

    return violations


def run_checks(
    bootstrap_dir: Path,
    tfvars_files: Iterable[Path],
    display_root: Path,
) -> list[Violation]:
    violations: list[Violation] = []

    for path in sorted(bootstrap_dir.glob("*.tf")):
        violations.extend(scan_terraform_file(path, display_root))

    declared_variables = declared_bootstrap_variables(bootstrap_dir)
    for path in tfvars_files:
        violations.extend(scan_tfvars_file(path, declared_variables, display_root))

    return sorted(violations, key=lambda item: (str(item.path), item.line, item.message))


def self_test() -> int:
    failures: list[str] = []

    forbidden_samples = {
        'provider "kubernetes" {}': "Kubernetes provider",
        'resource "helm_release" "argocd" {}': "Helm release",
        'resource "kubernetes_namespace_v1" "runtime" {}': "Kubernetes resource",
        'output "piraeus_namespace" { value = "piraeus" }': "platform output",
        'kind = "ExternalSecret"': "runtime kind",
        'apiVersion = "argoproj.io/v1alpha1"': "runtime API group",
        "kind: ClusterIssuer": "runtime YAML kind",
        "apiVersion: external-secrets.io/v1": "runtime YAML API group",
        'path = "../argocd/bootstrap"': "cross-layer path",
        'path = "secret/data/platform/forgejo/admin"': "runtime secret path",
    }

    for sample, label in forbidden_samples.items():
        active = active_hcl(sample)
        detected = any(pattern.search(active) for pattern, _ in FORBIDDEN_SOURCE_PATTERNS)
        if not detected:
            block_match = re.search(
                r'(?m)^\s*(variable|output)\s+"([^"]+)"\s*\{', active
            )
            detected = bool(
                block_match and name_crosses_boundary(block_match.group(2))
            )
        if not detected:
            failures.append(f"did not reject {label}")

    allowed_samples = (
        'data "helm_template" "cilium" {}',
        'resource "local_sensitive_file" "kubeconfig" {}',
        '// piraeus dependencies\nmodules = [{ name = "drbd" }]',
        'apiVersion = "cilium.io/v2"',
    )
    for sample in allowed_samples:
        active = active_hcl(sample)
        if any(pattern.search(active) for pattern, _ in FORBIDDEN_SOURCE_PATTERNS):
            failures.append(f"rejected allowed sample: {sample!r}")

    tfvars_sample = """
      proxmox = {
        endpoint = "https://pve.example.com:8006"
      }
        argocd_host = "argocd.example.com"
    """
    assignments = [name for name, _ in top_level_tfvars_assignments(tfvars_sample)]
    if assignments != ["proxmox", "argocd_host"]:
        failures.append(
            f"incorrect top-level tfvars assignments detected: {assignments!r}"
        )

    if failures:
        for failure in failures:
            print(f"[bootstrap-isolation] self-test failed: {failure}", file=sys.stderr)
        return 1

    print("[bootstrap-isolation] self-test passed")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check that bootstrap/ does not own platform/runtime resources."
    )
    parser.add_argument(
        "--bootstrap-dir",
        type=Path,
        default=DEFAULT_BOOTSTRAP_DIR,
        help="Bootstrap directory to scan.",
    )
    parser.add_argument(
        "--tfvars",
        type=Path,
        action="append",
        help="Tracked tfvars file to compare with bootstrap variable declarations.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run in-memory positive and negative rule tests.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()

    bootstrap_dir = args.bootstrap_dir.resolve()
    tfvars_files = tuple(
        path.resolve() for path in (args.tfvars or DEFAULT_TFVARS_FILES)
    )

    violations = run_checks(bootstrap_dir, tfvars_files, PROJECT_ROOT)
    if violations:
        for violation in violations:
            print(
                f"{violation.path}:{violation.line}: "
                f"bootstrap isolation violation: {violation.message}",
                file=sys.stderr,
            )
        print(
            f"[bootstrap-isolation] failed with {len(violations)} violation(s)",
            file=sys.stderr,
        )
        return 1

    print(
        "[bootstrap-isolation] passed: bootstrap owns only "
        "Proxmox, Talos, local artifacts, and Cilium bootstrap"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
