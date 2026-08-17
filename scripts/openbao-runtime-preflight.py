#!/usr/bin/env python3
# Bootstrap role: no-deploy (runtime secret contract validation only).

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


EXPECTED_CONTRACT: dict[str, dict[str, Any]] = {
    "platform/cert-manager/cloudflare": {
        "app": "cert-manager/cloudflare-dns01",
        "properties": {"api_token": "nonempty"},
    },
    "platform/authentik/runtime": {
        "app": "authentik",
        "properties": {
            "secret_key": "nonempty",
            "bootstrap_password": "nonempty",
        },
    },
    "platform/authentik/platform-admin": {
        "app": "authentik/platform-administrator",
        "properties": {"password": "nonempty"},
        "manifest_required": False,
    },
    "platform/authentik/postgresql": {
        "app": "authentik",
        "properties": {"password": "nonempty"},
    },
    "platform/authentik/redis": {
        "app": "authentik",
        "properties": {"password": "nonempty"},
    },
    "platform/forgejo/admin": {
        "app": "forgejo",
        "properties": {"username": "nonempty", "password": "nonempty"},
    },
    "platform/forgejo/postgresql": {
        "app": "forgejo",
        "properties": {"password": "nonempty"},
    },
    "platform/forgejo/valkey": {
        "app": "forgejo",
        "properties": {"password": "nonempty"},
    },
    "platform/forgejo/oidc": {
        "app": "forgejo",
        "properties": {"client_id": "nonempty", "client_secret": "nonempty"},
    },
    "platform/argocd/oidc": {
        "app": "authentik/argocd",
        "properties": {"client_id": "nonempty", "client_secret": "nonempty"},
    },
    "platform/harbor/runtime": {
        "app": "harbor",
        "properties": {
            "admin_password": "nonempty",
            "secret_key": "nonempty",
            "core_secret": "nonempty",
            "xsrf_key": "nonempty",
            "jobservice_secret": "nonempty",
            "registry_http_secret": "nonempty",
            "registry_password": "nonempty",
            "registry_htpasswd": "bcrypt_htpasswd",
        },
    },
    "platform/harbor/postgresql": {
        "app": "harbor",
        "properties": {"password": "nonempty"},
    },
    "platform/harbor/valkey": {
        "app": "harbor",
        "properties": {"password": "nonempty"},
    },
    "platform/harbor/oidc": {
        "app": "authentik/harbor",
        "properties": {"client_id": "nonempty", "client_secret": "nonempty"},
    },
    "platform/stalwart/runtime": {
        "app": "stalwart",
        "properties": {"recovery_admin_password": "nonempty"},
    },
    "platform/observability/grafana": {
        "app": "observability/grafana",
        "properties": {"username": "nonempty", "password": "nonempty"},
    },
    "platform/observability/grafana-oidc": {
        "app": "authentik/grafana",
        "properties": {"client_id": "nonempty", "client_secret": "nonempty"},
    },
    "platform/woodpecker/runtime": {
        "app": "woodpecker",
        "properties": {
            "agent_secret": "nonempty",
            "forgejo_client": "nonempty",
            "forgejo_secret": "nonempty",
        },
    },
    "platform/garage/runtime": {
        "app": "garage",
        "properties": {
            "rpc_secret": "nonempty",
            "admin_token": "nonempty",
            "metrics_token": "nonempty",
        },
    },
    "platform/velero/s3": {
        "app": "velero",
        "properties": {"access_key_id": "nonempty", "secret_access_key": "nonempty"},
    },
}

BCRYPT_HTPASSWD_PATTERN = re.compile(
    r"^[^:\r\n]+:\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}$"
)


def run(cmd: list[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=not allow_failure, capture_output=True, text=True)


def load_yaml(path: Path) -> Any:
    result = run(["yq", "eval", "-o=json", ".", str(path)])
    return json.loads(result.stdout)


def validate_property_shape(path: str, key: str, value: Any, validator: str) -> str | None:
    if validator == "nonempty":
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return "is empty"
        if isinstance(value, str) and value.strip().startswith("REPLACE_WITH_"):
            return "still contains a REPLACE_WITH_* placeholder"
        return None
    if validator == "bcrypt_htpasswd":
        if isinstance(value, str) and value.strip().startswith("REPLACE_WITH_"):
            return "still contains a REPLACE_WITH_* placeholder"
        if not isinstance(value, str) or BCRYPT_HTPASSWD_PATTERN.fullmatch(
            value.strip()
        ) is None:
            return "does not look like a username:bcrypt htpasswd line"
        return None
    return None


def validate_internal_shape_contract() -> list[str]:
    issues: list[str] = []
    bcrypt_payload = "A" * 53

    for variant in ("a", "b", "y"):
        value = f"harbor_registry_user:$2{variant}$10${bcrypt_payload}"
        error = validate_property_shape(
            "platform/harbor/runtime",
            "registry_htpasswd",
            value,
            "bcrypt_htpasswd",
        )
        if error:
            issues.append(f"valid $2{variant}$ htpasswd line rejected: {error}")

    for label, value in {
        "hash without username": f"$2y$10${bcrypt_payload}",
        "unsupported bcrypt variant": (
            f"harbor_registry_user:$2x$10${bcrypt_payload}"
        ),
        "placeholder": "REPLACE_WITH_BCRYPT_HTPASSWD_LINE",
    }.items():
        error = validate_property_shape(
            "platform/harbor/runtime",
            "registry_htpasswd",
            value,
            "bcrypt_htpasswd",
        )
        if error is None:
            issues.append(f"invalid {label} accepted")

    return issues


def collect_manifest_contract(root: Path) -> dict[str, set[str]]:
    manifest_contract: dict[str, set[str]] = defaultdict(set)
    for path in sorted((root / "argocd/platform").glob("**/*.[Yy][Aa][Mm][Ll]")):
        data = load_yaml(path)
        if not isinstance(data, dict) or data.get("kind") != "ExternalSecret":
            continue
        spec = data.get("spec", {})
        if spec.get("secretStoreRef", {}).get("name") != "openbao":
            continue
        for item in spec.get("data", []):
            remote_ref = item.get("remoteRef", {})
            key = remote_ref.get("key")
            prop = remote_ref.get("property")
            if key and prop:
                manifest_contract[key].add(prop)
    return manifest_contract


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only runtime secret preflight against OpenBao for GitOps bootstrap.",
    )
    parser.add_argument(
        "--mount-path",
        default="secret",
        help="OpenBao KV mount path used by the ClusterSecretStore.",
    )
    parser.add_argument(
        "--bao-addr",
        default=os.environ.get("BAO_ADDR", "http://127.0.0.1:8200"),
        help="OpenBao address. Defaults to BAO_ADDR or http://127.0.0.1:8200.",
    )
    parser.add_argument(
        "--require-final",
        action="store_true",
        help="Fail when a path still carries bootstrap_provisional=true.",
    )
    parser.add_argument(
        "--contract-only",
        action="store_true",
        help="Validate generator and ExternalSecret contract without contacting OpenBao.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]

    manifest_contract = collect_manifest_contract(root)
    manifest_drift = [
        f"internal shape contract: {issue}"
        for issue in validate_internal_shape_contract()
    ]
    for secret_path, meta in EXPECTED_CONTRACT.items():
        if not meta.get("manifest_required", True):
            continue
        expected_props = set(meta["properties"].keys())
        actual_props = manifest_contract.get(secret_path, set())
        missing_props = sorted(expected_props - actual_props)
        if missing_props:
            manifest_drift.append(
                f"{secret_path}: ExternalSecret manifests do not consume required properties {', '.join(missing_props)}"
            )

    generator_result = run(
        [
            "bash",
            str(root / "scripts/generate-runtime-secret-puts.sh"),
            "--list-contract",
        ]
    )
    generator_contract: dict[str, set[str]] = {}
    for line in generator_result.stdout.splitlines():
        if not line.strip():
            continue
        secret_path, raw_properties = line.strip().split(":", 1)
        generator_contract[secret_path] = set(raw_properties.split(","))

    generator_paths = set(generator_contract)
    expected_paths = set(EXPECTED_CONTRACT)
    for secret_path in sorted(expected_paths - generator_paths):
        manifest_drift.append(
            f"{secret_path}: runtime secret seed generator does not create this path"
        )
    for secret_path in sorted(generator_paths - expected_paths):
        manifest_drift.append(
            f"{secret_path}: runtime secret seed generator path is not in the expected contract"
        )
    for secret_path in sorted(expected_paths & generator_paths):
        expected_props = set(EXPECTED_CONTRACT[secret_path]["properties"])
        generated_props = generator_contract[secret_path]
        missing_props = sorted(expected_props - generated_props)
        extra_props = sorted(generated_props - expected_props)
        if missing_props:
            manifest_drift.append(
                f"{secret_path}: runtime secret seed generator omits properties {', '.join(missing_props)}"
            )
        if extra_props:
            manifest_drift.append(
                f"{secret_path}: runtime secret seed generator has unexpected properties {', '.join(extra_props)}"
            )

    if manifest_drift:
        print("[openbao-preflight] manifest contract drift detected", file=sys.stderr)
        for issue in manifest_drift:
            print(f"  - {issue}", file=sys.stderr)
        return 1

    if args.contract_only:
        print(
            "[openbao-preflight] generator, expected keys, and ExternalSecret manifests are consistent"
        )
        return 0

    if not os.environ.get("BAO_TOKEN"):
        print("BAO_TOKEN is required for OpenBao runtime preflight.", file=sys.stderr)
        return 1

    status = run(["bao", "status", "-format=json"], allow_failure=True)
    if status.returncode != 0:
        print(status.stderr.strip() or status.stdout.strip(), file=sys.stderr)
        return 1

    status_json = json.loads(status.stdout)
    if not status_json.get("initialized", False):
        print("OpenBao is not initialized.", file=sys.stderr)
        return 1
    if status_json.get("sealed", True):
        print("OpenBao is sealed. Unseal it before GitOps bootstrap.", file=sys.stderr)
        return 1

    missing_paths: list[str] = []
    missing_keys: list[str] = []
    shape_errors: list[str] = []
    provisional_paths: list[str] = []
    ok_paths: list[str] = []

    for secret_path, meta in EXPECTED_CONTRACT.items():
        bao_path = f"{args.mount_path}/{secret_path}"
        result = run(["bao", "kv", "get", "-format=json", bao_path], allow_failure=True)
        if result.returncode != 0:
            missing_paths.append(bao_path)
            continue

        payload = json.loads(result.stdout)
        data = payload.get("data", {}).get("data", {})
        if str(data.get("bootstrap_provisional", "")).lower() == "true":
            provisional_paths.append(bao_path)
        current_missing_keys: list[str] = []
        current_shape_errors: list[str] = []
        for key, validator in meta["properties"].items():
            if key not in data:
                current_missing_keys.append(key)
                continue
            error = validate_property_shape(secret_path, key, data[key], validator)
            if error:
                current_shape_errors.append(f"{key} {error}")

        if current_missing_keys:
            missing_keys.append(f"{bao_path}: {', '.join(current_missing_keys)}")
        if current_shape_errors:
            shape_errors.append(f"{bao_path}: {', '.join(current_shape_errors)}")
        if not current_missing_keys and not current_shape_errors:
            ok_paths.append(bao_path)

    print("[openbao-preflight] runtime secret summary")
    print(f"  checked paths: {len(EXPECTED_CONTRACT)}")
    print(f"  healthy paths: {len(ok_paths)}")
    print(f"  missing paths: {len(missing_paths)}")
    print(f"  missing keys: {len(missing_keys)}")
    print(f"  shape errors: {len(shape_errors)}")
    print(f"  provisional paths: {len(provisional_paths)}")

    for group_name, issues in [
        ("missing path", missing_paths),
        ("missing key set", missing_keys),
        ("shape issue", shape_errors),
    ]:
        for issue in issues:
            print(f"  - {group_name}: {issue}")

    for issue in provisional_paths:
        print(f"  - provisional bootstrap credentials: {issue}")

    if missing_paths or missing_keys or shape_errors or (
        args.require_final and provisional_paths
    ):
        print(file=sys.stderr)
        if args.require_final and provisional_paths:
            print(
                "Next actions: replace provisional Woodpecker OAuth and Velero S3 paths with final credentials.",
                file=sys.stderr,
            )
        else:
            print(
                "Next actions: use task ops:seed-runtime-secrets, then populate any incomplete secret/platform/* entries documented in docs/day0-bootstrap.md.",
                file=sys.stderr,
            )
        return 1

    if provisional_paths:
        print(
            "[openbao-preflight] bootstrap may continue, but provisional integration credentials must be rotated before final readiness"
        )

    apps = sorted({meta["app"] for meta in EXPECTED_CONTRACT.values()})
    print("  covered apps: " + ", ".join(apps))
    print("[openbao-preflight] all required runtime secret paths and keys are present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
