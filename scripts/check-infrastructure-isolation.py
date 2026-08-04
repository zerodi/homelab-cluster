#!/usr/bin/env python3
"""Enforce the ownership and cluster-state dependency of infrastructure/."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INFRASTRUCTURE_DIR = PROJECT_ROOT / "infrastructure"
INFRASTRUCTURE_TASKFILE = PROJECT_ROOT / "tasks" / "infrastructure.yml"
TASK_VARIABLES_SCRIPT = PROJECT_ROOT / "scripts" / "task-vars.sh"

APPROVED_RESOURCES = {
    ("helm_release", "argocd"),
    ("helm_release", "cert_manager"),
    ("helm_release", "external_secrets"),
    ("helm_release", "openbao"),
    ("helm_release", "piraeus_operator"),
    ("helm_release", "trust_manager"),
    (
        "kubernetes_cluster_role_binding_v1",
        "external_secrets_openbao_auth_delegator",
    ),
    (
        "kubernetes_cluster_role_binding_v1",
        "openbao_kubernetes_auth_delegator",
    ),
    ("kubernetes_labels", "piraeus_namespace_pod_security"),
    ("kubernetes_labels", "trusted_namespace_argocd"),
    ("kubernetes_labels", "trusted_namespace_cert_manager"),
    ("kubernetes_manifest", "homelab_ca_clusterissuer"),
    ("kubernetes_manifest", "homelab_root_ca"),
    ("kubernetes_manifest", "homelab_trust_bundle"),
    ("kubernetes_manifest", "linstor_cluster"),
    ("kubernetes_manifest", "linstor_satellite_configuration_talos"),
    ("kubernetes_manifest", "selfsigned_clusterissuer"),
    ("kubernetes_namespace_v1", "piraeus"),
    ("kubernetes_storage_class_v1", "piraeus_replicated"),
    ("terraform_data", "argocd_ready"),
    ("terraform_data", "linstor_cluster_ready"),
    ("terraform_data", "linstor_csi_ready"),
    ("terraform_data", "piraeus_operator_ready"),
}

APPROVED_DATA_SOURCES = {
    ("terraform_remote_state", "cluster"),
}

APPROVED_READINESS_RESOURCES = {
    ("terraform_data", "argocd_ready"),
    ("terraform_data", "linstor_cluster_ready"),
    ("terraform_data", "linstor_csi_ready"),
    ("terraform_data", "piraeus_operator_ready"),
}

APPROVED_CLUSTER_OUTPUTS = {
    "kubeconfig_path",
    "worker_hostnames",
}

FORBIDDEN_SOURCE_PATTERNS = (
    (
        re.compile(
            r"(?i)\b(?:authentik|echo|forgejo|garage|grafana|harbor|hubble|"
            r"kyverno|loki|observability|otel|reloader|tempo|velero|"
            r"victoria[_-]?metrics|woodpecker)\b"
        ),
        "application/runtime identifiers belong to argocd/",
    ),
    (
        re.compile(r"(?i)(?:^|[\"/])\.\./argocd(?:[/\"]|$)"),
        "infrastructure must not read files from argocd/",
    ),
    (
        re.compile(
            r"(?i)apiVersion\s*[:=]\s*\"?"
            r"(?:argoproj\.io|apps|batch)/"
        ),
        "application/runtime Kubernetes API objects belong to argocd/",
    ),
    (
        re.compile(
            r"(?i)kind\s*[:=]\s*\"?"
            r"(?:Application|ApplicationSet|AppProject|CronJob|Deployment|"
            r"ExternalSecret|HTTPRoute|Job|StatefulSet)\b"
        ),
        "application/runtime Kubernetes kinds belong to argocd/",
    ),
    (
        re.compile(r'(?im)^\s*namespace\s*=\s*"default"\s*$'),
        "infrastructure must not create baseline resources in default namespace",
    ),
    (
        re.compile(r"(?i)(?:secret/data/)?platform/[a-z0-9_./-]+"),
        "infrastructure must not reference runtime secret paths",
    ),
)

MUTATING_LOCAL_EXEC_PATTERN = re.compile(
    r"(?i)\bkubectl\s+(?:annotate|apply|create|delete|edit|label|patch|replace|"
    r"scale|set)\b|\bkubectl\s+(?:cp|exec|expose|run)\b|"
    r"\bkubectl\s+rollout\s+restart\b|"
    r"\bhelm\s+(?:install|uninstall|upgrade)\b|"
    r"\b(?:bao|terraform|tofu)\s+(?:apply|delete|destroy|write)\b"
)

HELPER_SUFFIXES = {".fish", ".py", ".sh"}


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    message: str


@dataclass(frozen=True)
class HclBlock:
    kind: str
    type_name: str
    name: str
    start: int
    text: str


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


def find_block_end(text: str, opening_brace: int) -> int:
    depth = 0
    in_string = False
    escaped = False

    for index in range(opening_brace, len(text)):
        char = text[index]
        if escaped:
            escaped = False
        elif char == "\\" and in_string:
            escaped = True
        elif char == '"':
            in_string = not in_string
        elif not in_string and char == "{":
            depth += 1
        elif not in_string and char == "}":
            depth -= 1
            if depth == 0:
                return index + 1

    return len(text)


def extract_blocks(text: str) -> list[HclBlock]:
    pattern = re.compile(
        r'(?m)^\s*(resource|data)\s+"([^"]+)"\s+"([^"]+)"\s*\{'
        r'|^\s*(module)\s+"([^"]+)"\s*\{'
    )
    blocks: list[HclBlock] = []

    for match in pattern.finditer(text):
        if match.group(1):
            kind = match.group(1)
            type_name = match.group(2)
            name = match.group(3)
        else:
            kind = "module"
            type_name = ""
            name = match.group(5)

        opening_brace = text.find("{", match.start(), match.end())
        end = find_block_end(text, opening_brace)
        blocks.append(
            HclBlock(
                kind=kind,
                type_name=type_name,
                name=name,
                start=match.start(),
                text=text[match.start() : end],
            )
        )

    return blocks


def scan_source(
    text: str,
    path: Path,
    require_cluster_contract: bool = False,
) -> list[Violation]:
    active = active_hcl(text)
    violations: list[Violation] = []
    blocks = extract_blocks(active)

    for pattern, message in FORBIDDEN_SOURCE_PATTERNS:
        for match in pattern.finditer(active):
            violations.append(
                Violation(path, line_number(active, match.start()), message)
            )

    cluster_blocks: list[HclBlock] = []
    for block in blocks:
        address = (block.type_name, block.name)
        block_line = line_number(active, block.start)

        if block.kind == "module":
            violations.append(
                Violation(
                    path,
                    block_line,
                    f'module "{block.name}" is not approved for infrastructure/',
                )
            )
            continue

        if block.kind == "resource" and address not in APPROVED_RESOURCES:
            violations.append(
                Violation(
                    path,
                    block_line,
                    f'resource "{block.type_name}.{block.name}" is outside the '
                    "approved platform-bootstrap inventory",
                )
            )

        if block.kind == "data":
            if address not in APPROVED_DATA_SOURCES:
                violations.append(
                    Violation(
                        path,
                        block_line,
                        f'data source "{block.type_name}.{block.name}" is not approved',
                    )
                )
            if address == ("terraform_remote_state", "cluster"):
                cluster_blocks.append(block)

        if 'provisioner "local-exec"' in block.text:
            if address not in APPROVED_READINESS_RESOURCES:
                violations.append(
                    Violation(
                        path,
                        block_line,
                        "local-exec is allowed only in approved readiness resources",
                    )
                )
            if MUTATING_LOCAL_EXEC_PATTERN.search(block.text):
                violations.append(
                    Violation(
                        path,
                        block_line,
                        "local-exec must not mutate long-lived Kubernetes objects",
                    )
                )

    if require_cluster_contract:
        if len(cluster_blocks) != 1:
            violations.append(
                Violation(
                    path,
                    1,
                    "infrastructure must declare exactly one "
                    'data.terraform_remote_state.cluster dependency',
                )
            )
        else:
            cluster = cluster_blocks[0]
            cluster_line = line_number(active, cluster.start)
            if not re.search(r'(?m)^\s*backend\s*=\s*"local"\s*$', cluster.text):
                violations.append(
                    Violation(
                        path,
                        cluster_line,
                        "cluster dependency must use the local state backend",
                    )
                )
            if not re.search(
                r"(?m)^\s*path\s*=\s*var\.cluster_state_path\s*$",
                cluster.text,
            ):
                violations.append(
                    Violation(
                        path,
                        cluster_line,
                        "cluster state path must come from var.cluster_state_path",
                    )
                )
            if re.search(r"(?m)^\s*(?:count|for_each)\s*=", cluster.text):
                violations.append(
                    Violation(
                        path,
                        cluster_line,
                        "cluster state dependency must remain unconditional",
                    )
                )

    return violations


def scan_cluster_contract(
    combined_text: str,
    display_path: Path,
) -> list[Violation]:
    violations: list[Violation] = []
    active = active_hcl(combined_text)

    variable_match = re.search(
        r'(?ms)^\s*variable\s+"cluster_state_path"\s*\{(.*?)^\s*\}',
        active,
    )
    if not variable_match:
        violations.append(
            Violation(
                display_path,
                1,
                'required variable "cluster_state_path" is missing',
            )
        )
    elif not re.search(
        r'(?m)^\s*default\s*=\s*"\.\./cluster/terraform\.tfstate"\s*$',
        variable_match.group(1),
    ):
        violations.append(
            Violation(
                display_path,
                line_number(active, variable_match.start()),
                "cluster_state_path must default to "
                "../cluster/terraform.tfstate",
            )
        )

    referenced_outputs: set[str] = set()
    output_reference_patterns = (
        r"\blocal\.cluster_outputs\.([A-Za-z_][A-Za-z0-9_]*)",
        r'\blocal\.cluster_outputs\["([^"]+)"\]',
        r"\bdata\.terraform_remote_state\.cluster\.outputs\."
        r"([A-Za-z_][A-Za-z0-9_]*)",
        r'\bdata\.terraform_remote_state\.cluster\.outputs\["([^"]+)"\]',
    )
    for pattern in output_reference_patterns:
        referenced_outputs.update(re.findall(pattern, active))
    unapproved_outputs = referenced_outputs - APPROVED_CLUSTER_OUTPUTS
    for output in sorted(unapproved_outputs):
        match = re.search(rf'(?:"|\.){re.escape(output)}(?:"|\b)', active)
        violations.append(
            Violation(
                display_path,
                line_number(active, match.start()) if match else 1,
                f'cluster output "{output}" is not approved for infrastructure/',
            )
        )

    missing_outputs = APPROVED_CLUSTER_OUTPUTS - referenced_outputs
    for output in sorted(missing_outputs):
        violations.append(
            Violation(
                display_path,
                1,
                f'infrastructure must consume cluster output "{output}"',
            )
        )

    if not re.search(
        r"(?m)^\s*cluster_outputs\s*=\s*"
        r"data\.terraform_remote_state\.cluster\.outputs\s*$",
        active,
    ):
        violations.append(
            Violation(
                display_path,
                1,
                "cluster outputs must come from "
                "data.terraform_remote_state.cluster.outputs",
            )
        )

    return violations


def scan_task_contract(text: str, display_path: Path) -> list[Violation]:
    violations: list[Violation] = []
    required_patterns = (
        (
            r"render-environment-contract\.sh",
            "infrastructure tasks must resolve the effective root environment contract",
        ),
        (
            r"\.storage\.piraeus\.namespace",
            "Piraeus namespace must come from the root environment contract",
        ),
        (
            r"\.storage\.piraeus\.pool_name",
            "Piraeus pool name must come from the root environment contract",
        ),
        (
            r"\.storage\.piraeus\.device",
            "Piraeus device must come from the root environment contract",
        ),
        (
            r"(?:tofu -chdir=cluster output -json worker_hostnames|"
            r"cluster_output worker_hostnames json)",
            "Piraeus nodes must come from completed cluster state",
        ),
    )
    for pattern, message in required_patterns:
        if re.search(pattern, text) is None:
            violations.append(Violation(display_path, 1, message))

    stale_output = re.search(
        r"(?s)(?:cd infrastructure.*?tofu output|"
        r"tofu -chdir=infrastructure output).*?"
        r"piraeus_(?:namespace|storage_device|storage_pool_name|"
        r"storage_nodes_csv)",
        text,
    )
    if stale_output:
        violations.append(
            Violation(
                display_path,
                line_number(text, stale_output.start()),
                "storage bootstrap must not depend on outputs from an "
                "unfinished infrastructure apply",
            )
        )

    return violations


def run_checks(infrastructure_dir: Path, display_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    terraform_files = sorted(infrastructure_dir.glob("*.tf"))
    combined_parts: list[str] = []

    for path in terraform_files:
        text = path.read_text(encoding="utf-8")
        combined_parts.append(text)
        display_path = path.relative_to(display_root)
        violations.extend(
            scan_source(
                text,
                display_path,
                require_cluster_contract=path.name == "providers.tf",
            )
        )

    combined_text = "\n".join(combined_parts)
    violations.extend(
        scan_cluster_contract(
            combined_text,
            infrastructure_dir.relative_to(display_root),
        )
    )

    for path in infrastructure_dir.rglob("*"):
        if (
            path.is_file()
            and ".terraform" not in path.parts
            and path.suffix in HELPER_SUFFIXES
        ):
            violations.append(
                Violation(
                    path.relative_to(display_root),
                    1,
                    "helper scripts must live in the repository root scripts/",
                )
            )

    if infrastructure_dir == DEFAULT_INFRASTRUCTURE_DIR:
        task_contract = "\n".join(
            (
                INFRASTRUCTURE_TASKFILE.read_text(encoding="utf-8"),
                TASK_VARIABLES_SCRIPT.read_text(encoding="utf-8"),
            )
        )
        violations.extend(
            scan_task_contract(
                task_contract,
                INFRASTRUCTURE_TASKFILE.relative_to(display_root),
            )
        )

    return sorted(
        set(violations),
        key=lambda item: (str(item.path), item.line, item.message),
    )


def self_test() -> int:
    failures: list[str] = []

    allowed = '''
resource "helm_release" "cert_manager" {}
resource "terraform_data" "argocd_ready" {
  provisioner "local-exec" {
    command = "kubectl -n argocd rollout status deployment/argocd-server"
  }
}
'''
    if scan_source(allowed, Path("allowed.tf")):
        failures.append("rejected approved platform resources or readiness command")

    forbidden_samples = {
        'resource "kubernetes_deployment_v1" "authentik" {}': "runtime resource",
        'module "runtime" { source = "../argocd" }': "module/cross-layer source",
        'kind = "ExternalSecret"': "runtime Kubernetes kind",
        'namespace = "default"': "default namespace",
        'path = "secret/data/platform/forgejo/admin"': "runtime secret path",
        '''
resource "terraform_data" "argocd_ready" {
  provisioner "local-exec" {
    command = "kubectl apply -f runtime.yaml"
  }
}
''': "mutating local-exec",
    }

    for sample, label in forbidden_samples.items():
        if not scan_source(sample, Path("forbidden.tf")):
            failures.append(f"did not reject {label}")

    conditional_cluster = '''
data "terraform_remote_state" "cluster" {
  count   = var.enabled ? 1 : 0
  backend = "local"
  config = {
    path = var.cluster_state_path
  }
}
'''
    violations = scan_source(
        conditional_cluster,
        Path("providers.tf"),
        require_cluster_contract=True,
    )
    if not any("unconditional" in item.message for item in violations):
        failures.append("did not reject conditional cluster state dependency")

    contract_with_unapproved_output = '''
variable "cluster_state_path" {
  default = "../cluster/terraform.tfstate"
}
locals {
  cluster_outputs = data.terraform_remote_state.cluster.outputs
  kubeconfig      = local.cluster_outputs.kubeconfig_path
  workers         = local.cluster_outputs.worker_hostnames
  controlplanes   = data.terraform_remote_state.cluster.outputs.controlplane_ips
}
'''
    violations = scan_cluster_contract(
        contract_with_unapproved_output,
        Path("infrastructure"),
    )
    if not any('output "controlplane_ips"' in item.message for item in violations):
        failures.append("did not reject an unapproved cluster output")

    valid_task_contract = '''
ENVIRONMENT_CONTRACT_PATH:
  sh: ./scripts/render-environment-contract.sh
PIRAEUS_NAMESPACE:
  sh: yq eval '.storage.piraeus.namespace' "{{.ENVIRONMENT_CONTRACT_PATH}}"
PIRAEUS_POOL_NAME:
  sh: yq eval '.storage.piraeus.pool_name' "{{.ENVIRONMENT_CONTRACT_PATH}}"
PIRAEUS_DEVICE:
  sh: yq eval '.storage.piraeus.device' "{{.ENVIRONMENT_CONTRACT_PATH}}"
PIRAEUS_NODES:
  sh: tofu -chdir=cluster output -json worker_hostnames
'''
    if scan_task_contract(valid_task_contract, Path("tasks/infrastructure.yml")):
        failures.append("rejected the root env/cluster task contract")

    stale_task_contract = valid_task_contract + '''
PIRAEUS_NAMESPACE:
  sh: tofu -chdir=infrastructure output -raw piraeus_namespace
'''
    violations = scan_task_contract(
        stale_task_contract,
        Path("tasks/infrastructure.yml"),
    )
    if not any("unfinished infrastructure apply" in item.message for item in violations):
        failures.append("did not reject infrastructure output task dependency")

    if failures:
        for failure in failures:
            print(
                f"[infrastructure-isolation] self-test failed: {failure}",
                file=sys.stderr,
            )
        return 1

    print("[infrastructure-isolation] self-test passed")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check that infrastructure/ owns only platform bootstrap resources "
            "and still requires completed cluster state."
        )
    )
    parser.add_argument(
        "--infrastructure-dir",
        type=Path,
        default=DEFAULT_INFRASTRUCTURE_DIR,
        help="Infrastructure directory to scan.",
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

    infrastructure_dir = args.infrastructure_dir.resolve()
    violations = run_checks(infrastructure_dir, PROJECT_ROOT)
    if violations:
        for violation in violations:
            print(
                f"{violation.path}:{violation.line}: "
                f"infrastructure isolation violation: {violation.message}",
                file=sys.stderr,
            )
        print(
            f"[infrastructure-isolation] failed with "
            f"{len(violations)} violation(s)",
            file=sys.stderr,
        )
        return 1

    print(
        "[infrastructure-isolation] passed: infrastructure owns only approved "
        "platform bootstrap resources and requires cluster state"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
