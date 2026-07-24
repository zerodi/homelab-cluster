#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


EXPECTED_CONTRACT: dict[str, dict[str, Any]] = {
    "platform/authentik/runtime": {
        "app": "authentik",
        "properties": {"secret_key": "nonempty"},
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
    "platform/observability/grafana": {
        "app": "observability/grafana",
        "properties": {"username": "nonempty", "password": "nonempty"},
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


def run(cmd: list[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=not allow_failure, capture_output=True, text=True)


def load_yaml(path: Path) -> Any:
    result = run(["yq", "eval", "-o=json", ".", str(path)])
    return json.loads(result.stdout)


def validate_property_shape(path: str, key: str, value: Any, validator: str) -> str | None:
    if validator == "nonempty":
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return "is empty"
        return None
    if validator == "bcrypt_htpasswd":
        if not isinstance(value, str) or not value.startswith("$2"):
            return "does not look like a bcrypt htpasswd line"
        return None
    return None


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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]

    if not os.environ.get("BAO_TOKEN"):
        print("BAO_TOKEN is required for OpenBao runtime preflight.", file=sys.stderr)
        return 1

    manifest_contract = collect_manifest_contract(root)
    manifest_drift: list[str] = []
    for secret_path, meta in EXPECTED_CONTRACT.items():
        expected_props = set(meta["properties"].keys())
        actual_props = manifest_contract.get(secret_path, set())
        missing_props = sorted(expected_props - actual_props)
        if missing_props:
            manifest_drift.append(
                f"{secret_path}: ExternalSecret manifests do not consume required properties {', '.join(missing_props)}"
            )

    if manifest_drift:
        print("[openbao-preflight] manifest contract drift detected", file=sys.stderr)
        for issue in manifest_drift:
            print(f"  - {issue}", file=sys.stderr)
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
    ok_paths: list[str] = []

    for secret_path, meta in EXPECTED_CONTRACT.items():
        bao_path = f"{args.mount_path}/{secret_path}"
        result = run(["bao", "kv", "get", "-format=json", bao_path], allow_failure=True)
        if result.returncode != 0:
            missing_paths.append(bao_path)
            continue

        payload = json.loads(result.stdout)
        data = payload.get("data", {}).get("data", {})
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

    for group_name, issues in [
        ("missing path", missing_paths),
        ("missing key set", missing_keys),
        ("shape issue", shape_errors),
    ]:
        for issue in issues:
            print(f"  - {group_name}: {issue}")

    if missing_paths or missing_keys or shape_errors:
        print(file=sys.stderr)
        print(
            "Next actions: use task ops:generate-runtime-secret-puts, then populate the missing secret/platform/* entries documented in docs/day0-bootstrap.md and docs/backup-restore.md.",
            file=sys.stderr,
        )
        return 1

    apps = sorted({meta["app"] for meta in EXPECTED_CONTRACT.values()})
    print("  covered apps: " + ", ".join(apps))
    print("[openbao-preflight] all required runtime secret paths and keys are present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
