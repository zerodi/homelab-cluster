from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shlex
import signal
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import bcrypt
from ruamel.yaml import YAML, YAMLError

from homelabctl.environment import render_contract
from homelabctl.project import ROOT
from homelabctl.runtime import (
    CommandError,
    json_output,
    log,
    require,
    run,
    wait_until,
)
from homelabctl.yamlutil import get_path, load


def absolute(path: str | Path, base: Path = ROOT) -> Path:
    value = Path(path).expanduser()
    return value.resolve() if value.is_absolute() else (base / value).resolve()


def ensure_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise CommandError(f"{label} not found: {path}")
    return path


def kubectl(kubeconfig: Path, *args: str, check: bool = True) -> Any:
    return run(["kubectl", "--kubeconfig", kubeconfig, *args], check=check)


def contract(path: Path) -> dict[str, Any]:
    value = load(path)
    if not isinstance(value, dict):
        raise CommandError(f"environment contract must be a mapping: {path}")
    return value


def argocd_identity_contract_issues(
    oidc_config: str,
    rbac_data: dict[str, str],
    *,
    issuer: str,
    admin_group: str,
) -> list[str]:
    """Return safe, value-free diagnostics for the Argo CD identity contract."""
    issues: list[str] = []
    try:
        parsed = YAML(typ="safe").load(oidc_config) or {}
    except YAMLError:
        parsed = {}
        issues.append("oidc.config is not valid YAML")
    expected_scopes = {"openid", "profile", "email", "groups"}
    if parsed.get("issuer") != issuer:
        issues.append("OIDC issuer does not match the environment contract")
    if parsed.get("clientID") != "$argocd-oidc:client_id":
        issues.append("OIDC clientID is not Secret-backed")
    if parsed.get("clientSecret") != "$argocd-oidc:client_secret":
        issues.append("OIDC clientSecret is not Secret-backed")
    if set(parsed.get("requestedScopes", [])) != expected_scopes:
        issues.append("OIDC requestedScopes do not contain the required scopes")
    if rbac_data.get("scopes") != "[groups]":
        issues.append("RBAC scopes are not restricted to groups")
    if rbac_data.get("policy.default") != "role:authenticated":
        issues.append("RBAC default role is not role:authenticated")
    if f"g, {admin_group}, role:admin" not in rbac_data.get("policy.csv", ""):
        issues.append("administrator group is not mapped to role:admin")
    return issues


def _https_json(
    url: str,
    root_ca: Path,
    *,
    method: str = "GET",
    payload: dict[str, str] | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    context = ssl.create_default_context(cafile=str(root_ca))
    try:
        with urllib.request.urlopen(request, context=context, timeout=20) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise CommandError(f"Argo CD API request failed with HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise CommandError(f"Argo CD API request failed: {exc.reason}") from None
    return json.loads(raw or b"{}")


def _argocd_login(base_url: str, root_ca: Path, password: str) -> str:
    response = _https_json(
        f"{base_url}/api/v1/session",
        root_ca,
        method="POST",
        payload={"username": "admin", "password": password},
    )
    token = response.get("token", "")
    if not token:
        raise CommandError("Argo CD local admin login did not return a session token")
    return str(token)


def _bao_secret(path: str) -> dict[str, str] | None:
    result = run(["bao", "kv", "get", "-format=json", path], check=False)
    if result.returncode:
        return None
    payload = json.loads(result.stdout)
    return payload.get("data", {}).get("data", {})


def argocd_access_finalize(kubeconfig: Path, contract_path: Path, root_ca: Path) -> int:
    """Rotate the bootstrap password, verify break-glass login, then remove its Secret."""
    if not os.environ.get("BAO_TOKEN"):
        raise CommandError("BAO_TOKEN is required")
    ensure_file(root_ca, "homelab root CA")
    env = contract(contract_path)
    base_url = f"https://{env['hosts']['argocd']}"
    mount = os.environ.get("BAO_KV_MOUNT", "secret")
    bao_path = f"{mount}/platform/argocd/admin"

    bootstrap = kubectl(
        kubeconfig,
        "-n",
        "argocd",
        "get",
        "secret",
        "argocd-initial-admin-secret",
        "-o",
        "json",
        check=False,
    )
    bootstrap_password = ""
    if bootstrap.returncode == 0:
        encoded = json.loads(bootstrap.stdout).get("data", {}).get("password", "")
        bootstrap_password = base64.b64decode(encoded).decode() if encoded else ""

    stored = _bao_secret(bao_path)
    stored_password = str((stored or {}).get("password", ""))
    if stored_password:
        try:
            _argocd_login(base_url, root_ca, stored_password)
            print("PASS Argo CD break-glass password from OpenBao")
            if bootstrap.returncode == 0:
                kubectl(
                    kubeconfig,
                    "-n",
                    "argocd",
                    "delete",
                    "secret",
                    "argocd-initial-admin-secret",
                )
                print("PASS Argo CD bootstrap Secret removed")
            else:
                print("PASS Argo CD bootstrap Secret already absent")
            return 0
        except CommandError:
            if not bootstrap_password:
                raise CommandError(
                    "OpenBao break-glass password is invalid and bootstrap Secret is absent"
                ) from None

    if not bootstrap_password:
        raise CommandError("Argo CD bootstrap Secret is absent and no break-glass password exists")
    token = _argocd_login(base_url, root_ca, bootstrap_password)
    print("PASS Argo CD bootstrap local-admin login")

    password_needs_replacement = not 8 <= len(stored_password) <= 32
    new_password = (
        random_value(
            32,
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._~!@#%^*-+=",
        )
        if password_needs_replacement
        else stored_password
    )
    if password_needs_replacement:
        bao_temp_put(bao_path, {"username": "admin", "password": new_password})
        print("PASS Argo CD break-glass password stored in OpenBao")
    _https_json(
        f"{base_url}/api/v1/account/password",
        root_ca,
        method="PUT",
        payload={"currentPassword": bootstrap_password, "newPassword": new_password},
        token=token,
    )
    _argocd_login(base_url, root_ca, new_password)
    print("PASS Argo CD rotated break-glass login")
    kubectl(
        kubeconfig,
        "-n",
        "argocd",
        "delete",
        "secret",
        "argocd-initial-admin-secret",
    )
    print("PASS Argo CD bootstrap Secret removed")
    return 0


def render_environment(base: str, override: str, output: str) -> int:
    path = render_contract(absolute(base), absolute(override), absolute(output))
    print(path)
    return 0


def tofu_output(name: str, fmt: str = "raw") -> str:
    result = run(["tofu", f"-chdir={ROOT / 'cluster'}", "output", f"-{fmt}", name], check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def task_var(command: str, values: list[str]) -> int:
    if command == "environment-contract":
        configured = os.environ.get("ENVIRONMENT_CONTRACT_PATH")
        legacy = os.environ.get("TF_VAR_environment_contract_path")
        if configured:
            print(absolute(configured))
        elif legacy:
            print(absolute(legacy, ROOT / "cluster"))
        else:
            render_environment(
                "envs/homelab.yaml", "envs/homelab.override.yaml", "out/homelab.effective.yaml"
            )
        return 0
    if command in {"kubeconfig", "talosconfig"}:
        env_name = "KUBECONFIG" if command == "kubeconfig" else "TALOSCONFIG"
        configured = os.environ.get(env_name)
        if command == "kubeconfig":
            configured = configured or os.environ.get("TF_VAR_kubeconfig_path")
        if configured:
            base = ROOT / "infrastructure" if command == "kubeconfig" else ROOT
            print(absolute(configured, base))
        else:
            output = tofu_output(f"{command}_path")
            if output:
                print(absolute(output, ROOT / "cluster"))
        return 0
    if command == "cluster-output":
        if not values:
            raise CommandError("cluster-output requires a name")
        value = tofu_output(values[0], values[1] if len(values) > 1 else "raw")
        if value:
            print(value)
        return 0
    if command == "contract-value":
        if len(values) != 2:
            raise CommandError("contract-value requires path and override environment name")
        override = os.environ.get(values[1])
        if override:
            print(override)
            return 0
        effective = os.environ.get("ENVIRONMENT_CONTRACT_PATH") or str(
            ROOT / "out/homelab.effective.yaml"
        )
        value = get_path(contract(absolute(effective)), values[0], "")
        print(json.dumps(value) if isinstance(value, (dict, list)) else value)
        return 0
    if command == "piraeus-nodes":
        configured = os.environ.get("TF_VAR_piraeus_storage_nodes")
        value = (
            json.loads(configured)
            if configured
            else json.loads(tofu_output("worker_hostnames", "json") or "[]")
        )
        print(" ".join(value))
        return 0
    raise CommandError(f"unknown task variable command: {command}")


def reconcile_cilium() -> int:
    require("tofu", "kubectl")
    kubeconfig = absolute(tofu_output("kubeconfig_path"), ROOT / "cluster")
    ensure_file(kubeconfig, "kubeconfig")
    manifest = tofu_output("cilium_lb_pool_manifest")
    wait_until(
        lambda: (
            kubectl(
                kubeconfig, "get", "crd/ciliumloadbalancerippools.cilium.io", check=False
            ).returncode
            == 0
        ),
        600,
        2,
        "CiliumLoadBalancerIPPool CRD",
    )
    run(["kubectl", "--kubeconfig", kubeconfig, "apply", "-f", "-"], input_text=manifest)
    print(
        kubectl(
            kubeconfig,
            "get",
            "ciliumloadbalancerippool",
            "external",
            "-o",
            "jsonpath={.spec.blocks}",
        ).stdout
    )
    return 0


def argocd_status(kubeconfig: Path, app: str, field: str) -> str:
    result = kubectl(
        kubeconfig,
        "-n",
        "argocd",
        "get",
        "application",
        app,
        "-o",
        f"jsonpath={{.status.{field}.status}}",
        check=False,
    )
    return result.stdout.strip()


def wait_argocd(kubeconfig: Path, app: str, timeout: int = 600) -> None:
    for field, expected in (("sync", "Synced"), ("health", "Healthy")):
        log("argocd", f"waiting for Application/{app} {field}={expected}")
        wait_until(
            lambda field=field, expected=expected: (
                argocd_status(kubeconfig, app, field) == expected
            ),
            timeout,
            5,
            f"Application/{app} {field}={expected}",
        )


def argocd_apply(kubeconfig: Path, root_manifest: Path, timeout: int, test_ssh: bool) -> int:
    require("kubectl")
    ensure_file(kubeconfig, "kubeconfig")
    kubectl(kubeconfig, "get", "namespace", "argocd")
    kubectl(
        kubeconfig,
        "wait",
        "--for=condition=Established",
        f"--timeout={timeout}s",
        "crd/applications.argoproj.io",
    )
    kubectl(
        kubeconfig,
        "-n",
        "argocd",
        "rollout",
        "status",
        f"--timeout={timeout}s",
        "deploy/argocd-server",
    )
    placeholder = any(
        "git.example.invalid/replace-me/gitops.git" in p.read_text(errors="ignore")
        for p in (ROOT / "argocd").rglob("*")
        if p.is_file()
    )
    if test_ssh or placeholder:
        files = [
            ROOT / "test-ssh-git/keys/known_hosts",
            ROOT / "test-ssh-git/templates/argocd-repository-secret.yaml",
            ROOT / "test-ssh-git/templates/root-application-ssh.yaml",
        ]
        if not all(p.is_file() for p in files):
            raise CommandError(
                "test-ssh-git artifacts are missing while repository coordinates are placeholders"
            )
        generated = kubectl(
            kubeconfig,
            "-n",
            "argocd",
            "create",
            "configmap",
            "argocd-ssh-known-hosts-cm",
            f"--from-file=ssh_known_hosts={files[0]}",
            "-o",
            "yaml",
            "--dry-run=client",
        ).stdout
        run(["kubectl", "--kubeconfig", kubeconfig, "apply", "-f", "-"], input_text=generated)
        kubectl(kubeconfig, "apply", "-f", str(files[1]))
        kubectl(kubeconfig, "apply", "-f", str(files[2]))
        wait_argocd(kubeconfig, "root-ssh", timeout)
        return 0
    kubectl(kubeconfig, "apply", "-n", "argocd", "-f", str(root_manifest))
    kubectl(
        kubeconfig,
        "-n",
        "argocd",
        "annotate",
        "application",
        "root",
        "argocd.argoproj.io/refresh=hard",
        "--overwrite",
    )
    wait_argocd(kubeconfig, "root", timeout)
    return 0


def bootstrap_linstor(
    kubeconfig: Path, namespace: str, pool: str, device: str, nodes: list[str]
) -> int:
    kubectl(kubeconfig, "linstor", "--help")
    kubectl(
        kubeconfig,
        "wait",
        "pod",
        "--timeout=15m",
        "--for=condition=Ready",
        "-n",
        namespace,
        "-l",
        "app.kubernetes.io/name=piraeus-datastore",
    )
    wait_until(
        lambda: (
            kubectl(
                kubeconfig, "-n", namespace, "get", "linstorcluster/linstor", check=False
            ).returncode
            == 0
        ),
        900,
        5,
        "LinstorCluster/linstor",
    )
    kubectl(
        kubeconfig,
        "wait",
        "--timeout=15m",
        "-n",
        namespace,
        "--for=condition=Available",
        "linstorcluster/linstor",
    )
    for node in nodes:
        wait_until(
            lambda n=node: (
                "DfltDisklessStorPool"
                in kubectl(
                    kubeconfig, "linstor", "storage-pool", "list", "--node", n, check=False
                ).stdout
            ),
            300,
            3,
            f"default diskless pool on {node}",
        )
        current = kubectl(
            kubeconfig,
            "linstor",
            "storage-pool",
            "list",
            "--node",
            node,
            "--storage-pool",
            pool,
            check=False,
        ).stdout
        if pool not in current:
            kubectl(
                kubeconfig,
                "linstor",
                "physical-storage",
                "create-device-pool",
                "--pool-name",
                pool,
                "--storage-pool",
                pool,
                "lvm",
                node,
                device,
            )
            wait_until(
                lambda n=node: (
                    pool
                    in kubectl(
                        kubeconfig,
                        "linstor",
                        "storage-pool",
                        "list",
                        "--node",
                        n,
                        "--storage-pool",
                        pool,
                        check=False,
                    ).stdout
                ),
                300,
                3,
                f"storage pool {pool} on {node}",
            )
    return 0


def bao_temp_put(path: str, data: dict[str, Any], cas: int | None = None) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        temp = Path(handle.name)
        os.chmod(temp, 0o600)
        json.dump(data, handle)
    try:
        args = ["bao", "kv", "put"]
        if cas is not None:
            args.append(f"-cas={cas}")
        run([*args, path, f"@{temp}"])
    finally:
        temp.unlink(missing_ok=True)


SECRET_CONTRACT: dict[str, tuple[str, ...]] = {
    "platform/cert-manager/cloudflare": ("api_token",),
    "platform/authentik/runtime": ("secret_key", "bootstrap_password"),
    "platform/authentik/platform-admin": ("password",),
    "platform/authentik/postgresql": ("password",),
    "platform/authentik/redis": ("password",),
    "platform/forgejo/admin": ("username", "password"),
    "platform/forgejo/postgresql": ("password",),
    "platform/forgejo/valkey": ("password",),
    "platform/forgejo/oidc": ("client_id", "client_secret"),
    "platform/argocd/oidc": ("client_id", "client_secret"),
    "platform/harbor/runtime": (
        "admin_password",
        "secret_key",
        "core_secret",
        "xsrf_key",
        "jobservice_secret",
        "registry_http_secret",
        "registry_password",
        "registry_htpasswd",
    ),
    "platform/harbor/postgresql": ("password",),
    "platform/harbor/valkey": ("password",),
    "platform/harbor/oidc": ("client_id", "client_secret"),
    "platform/stalwart/runtime": ("recovery_admin_password",),
    "platform/observability/grafana": ("username", "password"),
    "platform/observability/grafana-oidc": ("client_id", "client_secret"),
    "platform/woodpecker/runtime": ("agent_secret", "forgejo_client", "forgejo_secret"),
    "platform/garage/runtime": ("rpc_secret", "admin_token", "metrics_token"),
    "platform/velero/s3": ("access_key_id", "secret_access_key"),
}


def random_value(
    length: int, alphabet: str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generated_secrets() -> dict[str, dict[str, Any]]:
    cloudflare = os.environ.get("CLOUDFLARE_API_TOKEN")
    admin = os.environ.get("PLATFORM_ADMIN_PASSWORD")
    if not cloudflare:
        raise CommandError("CLOUDFLARE_API_TOKEN is required")
    b64 = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._~!@#%^*-+="
    harbor_password = random_value(40)
    htpasswd = (
        "harbor_registry_user:"
        + bcrypt.hashpw(harbor_password.encode(), bcrypt.gensalt(rounds=10)).decode()
    )
    values: dict[str, dict[str, Any]] = {
        "platform/cert-manager/cloudflare": {"api_token": cloudflare},
        "platform/authentik/runtime": {
            "secret_key": random_value(64, b64),
            "bootstrap_password": random_value(40),
        },
        "platform/authentik/platform-admin": {"password": admin or random_value(40, b64)},
        "platform/authentik/postgresql": {"password": random_value(40, b64)},
        "platform/authentik/redis": {"password": random_value(40, b64)},
        "platform/forgejo/admin": {"username": "forgejo", "password": random_value(40)},
        "platform/forgejo/postgresql": {"password": random_value(40)},
        "platform/forgejo/valkey": {"password": random_value(40)},
        "platform/forgejo/oidc": {
            "client_id": random_value(32),
            "client_secret": random_value(64, b64),
        },
        "platform/argocd/oidc": {
            "client_id": random_value(32),
            "client_secret": random_value(64, b64),
        },
        "platform/harbor/runtime": {
            "admin_password": random_value(40),
            "secret_key": random_value(16),
            "core_secret": random_value(16),
            "xsrf_key": random_value(32),
            "jobservice_secret": random_value(16),
            "registry_http_secret": random_value(16),
            "registry_password": harbor_password,
            "registry_htpasswd": htpasswd,
        },
        "platform/harbor/postgresql": {"password": random_value(40)},
        "platform/harbor/valkey": {"password": random_value(40)},
        "platform/harbor/oidc": {
            "client_id": random_value(32),
            "client_secret": random_value(64, b64),
        },
        "platform/stalwart/runtime": {"recovery_admin_password": random_value(40)},
        "platform/observability/grafana": {"username": "admin", "password": random_value(32, b64)},
        "platform/observability/grafana-oidc": {
            "client_id": random_value(32),
            "client_secret": random_value(64, b64),
        },
        "platform/woodpecker/runtime": {
            "agent_secret": random_value(64, b64),
            "forgejo_client": os.environ.get("WOODPECKER_FORGEJO_CLIENT", random_value(32)),
            "forgejo_secret": os.environ.get("WOODPECKER_FORGEJO_SECRET", random_value(64, b64)),
        },
        "platform/garage/runtime": {
            "rpc_secret": random_value(64, "abcdef0123456789"),
            "admin_token": random_value(64, b64),
            "metrics_token": random_value(64, b64),
        },
        "platform/velero/s3": {
            "access_key_id": os.environ.get("VELERO_S3_ACCESS_KEY_ID", random_value(32)),
            "secret_access_key": os.environ.get(
                "VELERO_S3_SECRET_ACCESS_KEY", random_value(64, b64)
            ),
        },
    }
    if not os.environ.get("WOODPECKER_FORGEJO_CLIENT"):
        values["platform/woodpecker/runtime"]["bootstrap_provisional"] = True
    if not os.environ.get("VELERO_S3_ACCESS_KEY_ID"):
        values["platform/velero/s3"]["bootstrap_provisional"] = True
    for left, right in (
        ("WOODPECKER_FORGEJO_CLIENT", "WOODPECKER_FORGEJO_SECRET"),
        ("VELERO_S3_ACCESS_KEY_ID", "VELERO_S3_SECRET_ACCESS_KEY"),
    ):
        if bool(os.environ.get(left)) != bool(os.environ.get(right)):
            raise CommandError(f"{left} and {right} must be supplied together")
    return values


def secrets_command(mode: str) -> int:
    if mode == "list-paths":
        print("\n".join(SECRET_CONTRACT))
        return 0
    if mode == "list-contract":
        print("\n".join(f"{p}:{','.join(keys)}" for p, keys in SECRET_CONTRACT.items()))
        return 0
    values = generated_secrets()
    mount = os.environ.get("BAO_KV_MOUNT", "secret").strip("/")
    if mode == "print":
        print(
            "# WARNING: sensitive bootstrap credentials; do not save this output in Git or CI logs."
        )
        for path, data in values.items():
            arguments = " ".join(
                shlex.quote(f"{key}={str(value).lower() if isinstance(value, bool) else value}")
                for key, value in data.items()
            )
            print(f"bao kv put {shlex.quote(f'{mount}/{path}')} {arguments}")
        return 0
    require("bao")
    if not os.environ.get("BAO_TOKEN"):
        raise CommandError("BAO_TOKEN is required")
    run(["bao", "status"])
    created = preserved = 0
    for path, data in values.items():
        full = f"{mount}/{path}"
        current = run(["bao", "kv", "get", "-format=json", full], check=False)
        if current.returncode == 0:
            preserved += 1
            log("runtime-secrets", f"existing path preserved: {path}")
            continue
        if "No value found at" not in current.stderr + current.stdout:
            raise CommandError(f"cannot safely determine whether OpenBao path exists: {full}")
        bao_temp_put(full, data)
        created += 1
        log("runtime-secrets", f"created missing path: {path}")
    log("runtime-secrets", f"summary: created={created} preserved={preserved}")
    return 0


def openbao_day0(
    kubeconfig: Path,
    address: str,
    namespace: str,
    service_account: str,
    policy: str,
    role: str,
    mount: str,
) -> int:
    if not os.environ.get("BAO_TOKEN"):
        raise CommandError("BAO_TOKEN is required")
    kubectl(kubeconfig, "-n", namespace, "get", "serviceaccount", service_account)
    status = run(["bao", "status", "-format=json"], env={"BAO_ADDR": address}, check=False)
    payload = json.loads(status.stdout)
    if not payload.get("initialized") or payload.get("sealed"):
        raise CommandError("OpenBao must be initialized and unsealed")
    env = {"BAO_ADDR": address}
    mounts = json_output(["bao", "secrets", "list", "-format=json"], env=env)
    if f"{mount}/" not in mounts:
        run(["bao", "secrets", "enable", f"-path={mount}", "kv-v2"], env=env)
    auth = json_output(["bao", "auth", "list", "-format=json"], env=env)
    if "kubernetes/" not in auth:
        run(["bao", "auth", "enable", "kubernetes"], env=env)
    ca_data = kubectl(
        kubeconfig,
        "config",
        "view",
        "--raw",
        "--minify",
        "--flatten",
        "-o",
        "jsonpath={.clusters[0].cluster.certificate-authority-data}",
    ).stdout
    ca = base64.b64decode(ca_data).decode()
    run(
        [
            "bao",
            "write",
            "auth/kubernetes/config",
            "kubernetes_host=https://kubernetes.default.svc",
            f"kubernetes_ca_cert={ca}",
        ],
        env=env,
    )
    text = f'path "{mount}/data/platform/*" {{\n  capabilities = ["read"]\n}}\n\npath "{mount}/metadata/platform/*" {{\n  capabilities = ["read", "list"]\n}}\n'
    with tempfile.NamedTemporaryFile("w", delete=False) as handle:
        path = Path(handle.name)
        handle.write(text)
    try:
        run(["bao", "policy", "write", policy, path], env=env)
    finally:
        path.unlink(missing_ok=True)
    run(
        [
            "bao",
            "write",
            f"auth/kubernetes/role/{role}",
            f"bound_service_account_names={service_account}",
            f"bound_service_account_namespaces={namespace}",
            f"policies={policy}",
            "ttl=1h",
        ],
        env=env,
    )
    return 0


def port_forward(action: str, kubeconfig: Path | None) -> int:
    address = os.environ.get("OPENBAO_LOCAL_ADDRESS", "127.0.0.1")
    local = os.environ.get("OPENBAO_LOCAL_PORT", "8200")
    remote = os.environ.get("OPENBAO_REMOTE_PORT", "8200")
    namespace = os.environ.get("OPENBAO_NAMESPACE", "openbao")
    service = os.environ.get("OPENBAO_SERVICE", "openbao")
    pid_file = absolute(os.environ.get("OPENBAO_PORT_FORWARD_PID", "out/openbao-port-forward.pid"))
    log_file = absolute(os.environ.get("OPENBAO_PORT_FORWARD_LOG", "out/openbao-port-forward.log"))

    def pid() -> int | None:
        try:
            return int(pid_file.read_text().strip())
        except (OSError, ValueError):
            return None

    def alive(value: int) -> bool:
        try:
            os.kill(value, 0)
            return True
        except OSError:
            return False

    def expected(value: int) -> bool:
        process = run(["ps", "-p", str(value), "-o", "command="], check=False).stdout
        return all(
            marker in process
            for marker in ("kubectl", "port-forward", f"svc/{service}", f"{local}:{remote}")
        )

    existing = pid()
    if action == "status":
        if existing and alive(existing) and expected(existing):
            print(f"OpenBao port-forward is running: pid={existing} addr=http://{address}:{local}")
            return 0
        pid_file.unlink(missing_ok=True)
        print("OpenBao port-forward is not running.")
        return 1
    if action == "stop":
        if not existing or not alive(existing):
            pid_file.unlink(missing_ok=True)
            print("OpenBao port-forward is not running.")
            return 0
        if not expected(existing):
            raise CommandError(
                f"PID {existing} is not the expected OpenBao port-forward; refusing to stop it"
            )
        os.kill(existing, signal.SIGTERM)
        wait_until(lambda: not alive(existing), 5, 0.25, "OpenBao port-forward stop")
        pid_file.unlink(missing_ok=True)
        print("OpenBao port-forward stopped.")
        return 0
    if kubeconfig is None:
        raise CommandError("--kubeconfig is required for start")
    if existing and alive(existing):
        if expected(existing):
            print(f"OpenBao port-forward is already running: pid={existing}")
            return 0
        raise CommandError(f"PID file points to an unrelated process: {pid_file}")
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    stream = log_file.open("w")
    proc = subprocess.Popen(
        [
            "kubectl",
            "--kubeconfig",
            str(kubeconfig),
            "-n",
            namespace,
            "port-forward",
            "--address",
            address,
            f"svc/{service}",
            f"{local}:{remote}",
        ],
        stdout=stream,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    stream.close()
    pid_file.write_text(f"{proc.pid}\n")
    wait_until(
        lambda: (
            (log_file.exists() and "Forwarding from" in log_file.read_text(errors="ignore"))
            or proc.poll() is not None
        ),
        10,
        0.25,
        "OpenBao port-forward start",
    )
    if proc.poll() is not None:
        pid_file.unlink(missing_ok=True)
        raise CommandError(log_file.read_text(errors="ignore"))
    print(f"OpenBao port-forward started: pid={proc.pid} addr=http://{address}:{local}")
    return 0


def hosts_entries(kubeconfig: Path, contract_path: Path) -> int:
    env = contract(contract_path)
    resources = (
        ("argocd", "Ingress", "argocd", "argocd-server"),
        ("authentik", "Service", "authentik", "cilium-gateway-authentik"),
        ("forgejo", "Service", "forgejo", "cilium-gateway-forgejo"),
        ("garage", "Service", "garage", "cilium-gateway-garage"),
        ("harbor", "Service", "harbor", "cilium-gateway-harbor"),
        ("stalwart", "Service", "gateway", "cilium-gateway-external"),
        ("mail", "Service", "stalwart", "stalwart-mail"),
        ("woodpecker", "Service", "woodpecker", "cilium-gateway-woodpecker"),
        ("echo", "Service", "echo", "cilium-gateway-echo"),
        ("grafana", "Service", "observability", "cilium-gateway-grafana"),
        ("hubble", "Service", "gateway", "cilium-gateway-internal"),
    )
    missing = []
    for key, kind, namespace, name in resources:
        host = env.get("hosts", {}).get(key)
        result = kubectl(
            kubeconfig,
            "-n",
            namespace,
            "get",
            kind,
            name,
            "-o",
            "jsonpath={.status.loadBalancer.ingress[0].ip}",
            check=False,
        )
        if not host or not result.stdout.strip():
            missing.append(f"{namespace}/{name}")
        else:
            print(f"{result.stdout.strip()} {host}")
    if missing:
        raise CommandError("missing LoadBalancer addresses: " + ", ".join(missing))
    return 0


def garage(kubeconfig: Path, action: str) -> int:
    namespace = os.environ.get("GARAGE_NAMESPACE", "garage")
    pod = os.environ.get("GARAGE_POD", "garage-0")
    status = kubectl(kubeconfig, "-n", namespace, "exec", pod, "--", "/garage", "status").stdout
    if action == "status":
        print(status, end="")
        return 0
    override = os.environ.get("GARAGE_NODE_ID")
    ids = re.findall(r"(?m)^([0-9A-Fa-f]{16,64})\s+([^\s]+)", status)
    node = override or next(
        (i for i, n in ids if n == pod or n.startswith(pod + ".")),
        ids[0][0] if len(ids) == 1 else "",
    )
    if not node:
        raise CommandError("failed to detect Garage node id")
    if action == "detect-node-id":
        print(node)
        return 0
    zone = os.environ.get("GARAGE_ZONE", "homelab")
    capacity = os.environ.get("GARAGE_CAPACITY", "20G")
    bucket = os.environ.get("GARAGE_BUCKET", "homelab-velero")
    key = os.environ.get("GARAGE_KEY_NAME", "velero")
    if action == "bootstrap-velero":
        require("bao", "kubectl")
        if not os.environ.get("BAO_TOKEN"):
            raise CommandError("BAO_TOKEN is required for Garage/Velero bootstrap")

        buckets = kubectl(
            kubeconfig, "-n", namespace, "exec", pod, "--", "/garage", "bucket", "list"
        ).stdout
        if not re.search(rf"(?m)\s{re.escape(bucket)}(?:\s|$)", buckets):
            kubectl(
                kubeconfig,
                "-n",
                namespace,
                "exec",
                pod,
                "--",
                "/garage",
                "bucket",
                "create",
                bucket,
            )

        keys = kubectl(
            kubeconfig, "-n", namespace, "exec", pod, "--", "/garage", "key", "list"
        ).stdout
        if not re.search(rf"(?m)\s{re.escape(key)}(?:\s|$)", keys):
            kubectl(
                kubeconfig,
                "-n",
                namespace,
                "exec",
                pod,
                "--",
                "/garage",
                "key",
                "create",
                key,
            )

        kubectl(
            kubeconfig,
            "-n",
            namespace,
            "exec",
            pod,
            "--",
            "/garage",
            "bucket",
            "allow",
            "--read",
            "--write",
            "--owner",
            bucket,
            "--key",
            key,
        )
        key_info = kubectl(
            kubeconfig,
            "-n",
            namespace,
            "exec",
            pod,
            "--",
            "/garage",
            "key",
            "info",
            key,
            "--show-secret",
        ).stdout
        access_match = re.search(r"(?mi)^(?:Key|Access key) ID:\s*(\S+)\s*$", key_info)
        secret_match = re.search(r"(?mi)^Secret key:\s*(\S+)\s*$", key_info)
        if not access_match or not secret_match:
            raise CommandError("failed to parse Garage key credentials")
        run(
            [
                "bao",
                "kv",
                "put",
                "secret/platform/velero/s3",
                f"access_key_id={access_match.group(1)}",
                f"secret_access_key={secret_match.group(1)}",
            ]
        )
        print(f"Garage bucket {bucket} and key {key} are ready; credentials stored in OpenBao.")
        return 0
    for line in (
        f"kubectl -n {namespace} exec {pod} -- /garage layout assign -z {zone} -c {capacity} {node}",
        f"kubectl -n {namespace} exec {pod} -- /garage layout apply --version 1",
        f"kubectl -n {namespace} exec {pod} -- /garage bucket create {bucket}",
        f"kubectl -n {namespace} exec {pod} -- /garage key create {key}",
        f"kubectl -n {namespace} exec {pod} -- /garage bucket allow --read --write --owner {bucket} --key {key}",
        f"kubectl -n {namespace} exec {pod} -- /garage key info {key} --show-secret",
        "bao kv put secret/platform/velero/s3 access_key_id=REPLACE_WITH_GARAGE_KEY_ID secret_access_key=REPLACE_WITH_GARAGE_SECRET_KEY",
    ):
        print(line)
    return 0


def initial_credentials(kubeconfig: Path, contract_path: Path) -> int:
    if not os.environ.get("BAO_TOKEN"):
        raise CommandError("BAO_TOKEN is required")
    env = contract(contract_path)
    mount = os.environ.get("BAO_KV_MOUNT", "secret")

    def field(path: str, key: str) -> str:
        return run(["bao", "kv", "get", f"-field={key}", f"{mount}/{path}"]).stdout.strip()

    encoded = kubectl(
        kubeconfig,
        "-n",
        "argocd",
        "get",
        "secret",
        "argocd-initial-admin-secret",
        "-o",
        "jsonpath={.data.password}",
        check=False,
    ).stdout
    argocd_password = (
        base64.b64decode(encoded).decode()
        if encoded
        else field("platform/argocd/admin", "password")
    )
    rows = (
        (
            "Authentik",
            f"https://{env['hosts']['authentik']}/if/admin/",
            "akadmin",
            field("platform/authentik/runtime", "bootstrap_password"),
        ),
        (
            "Authentik Administrator",
            f"https://{env['hosts']['authentik']}/",
            env["identity"]["administrator"]["username"],
            field("platform/authentik/platform-admin", "password"),
        ),
        (
            "Argo CD",
            f"https://{env['hosts']['argocd']}",
            "admin",
            argocd_password,
        ),
        (
            "Forgejo",
            f"https://{env['hosts']['forgejo']}",
            field("platform/forgejo/admin", "username"),
            field("platform/forgejo/admin", "password"),
        ),
        (
            "Grafana",
            f"https://{env['hosts']['grafana']}",
            field("platform/observability/grafana", "username"),
            field("platform/observability/grafana", "password"),
        ),
        (
            "Harbor",
            f"https://{env['hosts']['harbor']}",
            "admin",
            field("platform/harbor/runtime", "admin_password"),
        ),
        (
            "Stalwart",
            f"https://{env['hosts']['stalwart']}/admin",
            "admin",
            field("platform/stalwart/runtime", "recovery_admin_password"),
        ),
    )
    print("APPLICATION\tURL\tLOGIN\tPASSWORD")
    for row in rows:
        print("\t".join(row))
    return 0


def application_operation_issues(payload: dict[str, Any], expected: set[str]) -> list[str]:
    issues: list[str] = []
    for item in payload.get("items", []):
        name = item.get("metadata", {}).get("name", "unknown")
        if name not in expected:
            continue
        state = item.get("status", {}).get("operationState") or {}
        phase = state.get("phase", "")
        if phase and phase != "Succeeded":
            message = state.get("message", "operation has not completed")
            issues.append(f"{name}: {phase}: {message}")
    return issues


def application_revision_issues(
    payload: dict[str, Any],
    *,
    root: str,
    expected_revision: str,
    critical_apps: set[str],
    critical_revision: str,
) -> list[str]:
    """Validate resolved root and staged critical Git revisions."""
    applications = {item.get("metadata", {}).get("name"): item for item in payload.get("items", [])}
    issues: list[str] = []
    root_app = applications.get(root, {})
    root_revision = str(root_app.get("status", {}).get("sync", {}).get("revision") or "")
    if root_revision != expected_revision:
        issues.append(f"{root}: resolved revision does not match the expected snapshot")
    for name in sorted(critical_apps):
        application = applications.get(name)
        if not application:
            issues.append(f"{name}: Application is missing")
            continue
        spec = application.get("spec", {})
        sources = list(spec.get("sources") or [])
        if spec.get("source"):
            sources.append(spec["source"])
        desired = {str(source.get("targetRevision") or "") for source in sources}
        sync = application.get("status", {}).get("sync", {})
        resolved = {str(value) for value in sync.get("revisions", [])}
        if sync.get("revision"):
            resolved.add(str(sync["revision"]))
        if critical_revision not in desired:
            issues.append(f"{name}: desired critical revision does not match the contract")
        if critical_revision not in resolved:
            issues.append(f"{name}: critical revision is not live")
    return issues


def pod_readiness_issues(payload: dict[str, Any], namespaces: set[str]) -> list[str]:
    issues: list[str] = []
    terminal_waiting_reasons = {
        "CrashLoopBackOff",
        "CreateContainerConfigError",
        "ErrImagePull",
        "ImagePullBackOff",
        "InvalidImageName",
        "RunContainerError",
    }
    for item in payload.get("items", []):
        metadata = item.get("metadata", {})
        namespace = metadata.get("namespace", "")
        if namespace not in namespaces:
            continue
        name = metadata.get("name", "unknown")
        phase = item.get("status", {}).get("phase", "Unknown")
        if phase == "Succeeded":
            continue
        if phase != "Running":
            issues.append(f"{namespace}/{name}: phase={phase}")
            continue
        pod_status = item.get("status", {})
        statuses = [
            *pod_status.get("initContainerStatuses", []),
            *pod_status.get("containerStatuses", []),
            *pod_status.get("ephemeralContainerStatuses", []),
        ]
        for status in statuses:
            container = status.get("name", "unknown")
            waiting = status.get("state", {}).get("waiting", {}).get("reason", "")
            if waiting in terminal_waiting_reasons:
                issues.append(f"{namespace}/{name}/{container}: {waiting}")
            elif not status.get("ready", False):
                issues.append(f"{namespace}/{name}/{container}: not ready")
    return issues


def latest_completed_backup_age_hours(
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
) -> tuple[str, float] | None:
    completed: list[tuple[str, datetime]] = []
    for item in payload.get("items", []):
        status = item.get("status", {})
        if status.get("phase") != "Completed" or not status.get("completionTimestamp"):
            continue
        timestamp = datetime.fromisoformat(status["completionTimestamp"])
        completed.append((item.get("metadata", {}).get("name", "unknown"), timestamp))
    if not completed:
        return None
    name, timestamp = max(completed, key=lambda entry: entry[1])
    current = now or datetime.now(UTC)
    return name, max(0.0, (current - timestamp).total_seconds() / 3600)


def latest_completed_restore_age_hours(
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
) -> tuple[str, float] | None:
    """Return the newest successful, explicitly labelled restore smoke test."""
    completed: list[tuple[str, datetime]] = []
    for item in payload.get("items", []):
        labels = item.get("metadata", {}).get("labels", {})
        status = item.get("status", {})
        if (
            labels.get("homelab.dev/restore-smoke") != "true"
            or labels.get("homelab.dev/restore-verified") != "true"
            or status.get("phase") != "Completed"
            or not status.get("completionTimestamp")
        ):
            continue
        timestamp = datetime.fromisoformat(status["completionTimestamp"])
        completed.append((item.get("metadata", {}).get("name", "unknown"), timestamp))
    if not completed:
        return None
    name, timestamp = max(completed, key=lambda entry: entry[1])
    current = now or datetime.now(UTC)
    return name, max(0.0, (current - timestamp).total_seconds() / 3600)


def kyverno_policy_report_issues(
    payload: dict[str, Any], allowed: set[str]
) -> tuple[list[str], set[str]]:
    """Return value-free Kyverno violations and the allowlist entries they used."""
    issues: list[str] = []
    used: set[str] = set()
    for report in payload.get("items", []):
        report_namespace = str(report.get("metadata", {}).get("namespace") or "cluster")
        for result in report.get("results", []):
            outcome = str(result.get("result") or "").lower()
            if outcome not in {"fail", "error", "warn"}:
                continue
            policy = str(result.get("policy") or "unknown")
            rule = str(result.get("rule") or "-")
            report_scope = report.get("scope") or {}
            resources = result.get("resources") or ([report_scope] if report_scope else [{}])
            for resource in resources:
                namespace = str(resource.get("namespace") or report_namespace)
                kind = str(resource.get("kind") or "unknown")
                name = str(resource.get("name") or "unknown")
                key = f"{namespace}/{policy}/{rule}/{kind}/{name}"
                if key in allowed:
                    used.add(key)
                else:
                    issues.append(f"{outcome}: {key}")
    return issues, used


def load_kyverno_allowlist(path: Path) -> set[str]:
    payload = load(path)
    entries = payload.get("exceptions", []) if isinstance(payload, dict) else None
    if not isinstance(entries, list) or any(not isinstance(entry, str) for entry in entries):
        raise CommandError(f"invalid Kyverno audit allowlist: {path}")
    if len(entries) != len(set(entries)):
        raise CommandError(f"duplicate Kyverno audit allowlist entry: {path}")
    return set(entries)


def telemetry_log_error_count(text: str) -> int:
    signatures = (
        "Failed to scrape Prometheus endpoint",
        "call to /stats/summary endpoint failed",
        "Dropping data",
        "sending queue is full",
        "no more retries left",
        "Exporting failed",
    )
    return sum(text.count(signature) for signature in signatures)


def otlp_trace_payload(trace_id: str, span_id: str, timestamp_ns: int) -> str:
    """Render one OTLP/HTTP JSON span using the protocol's hex ID encoding."""
    return json.dumps(
        {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "service.name",
                                "value": {"stringValue": "homelabctl-observability-smoke"},
                            },
                            {
                                "key": "deployment.environment.name",
                                "value": {"stringValue": "homelab"},
                            },
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "homelabctl", "version": "1"},
                            "spans": [
                                {
                                    "traceId": trace_id,
                                    "spanId": span_id,
                                    "name": "stage2-trace-roundtrip",
                                    "kind": 1,
                                    "startTimeUnixNano": str(timestamp_ns),
                                    "endTimeUnixNano": str(timestamp_ns + 1_000_000),
                                    "status": {"code": 1},
                                }
                            ],
                        }
                    ],
                }
            ]
        },
        separators=(",", ":"),
    )


def prometheus_metric_sum(text: str, metric: str, label: str) -> float:
    """Sum matching Prometheus samples; an absent failure series means zero."""
    total = 0.0
    prefix = metric + "{"
    for line in text.splitlines():
        if not line.startswith(prefix) or label not in line:
            continue
        try:
            total += float(line.rsplit(maxsplit=1)[1])
        except (IndexError, ValueError):
            continue
    return total


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def _https_redirect(url: str, root_ca: Path) -> tuple[int, str]:
    context = ssl.create_default_context(cafile=str(root_ca))
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        _NoRedirect(),
    )
    try:
        with opener.open(url, timeout=20) as response:
            return response.status, response.headers.get("Location", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Location", "")
    except urllib.error.URLError as exc:
        raise CommandError(f"HTTPS request failed: {exc.reason}") from None


def _authentik_primary_auth_component(
    login_url: str,
    authentik_url: str,
    username: str,
    password: str,
    root_ca: Path,
) -> str:
    """Run password authentication up to the MFA/redirect stage without exposing credentials."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cookies = Path(temp_dir) / "cookies"
        common = [
            "curl",
            "--silent",
            "--show-error",
            "--fail",
            "--cacert",
            root_ca,
            "--cookie",
            cookies,
            "--cookie-jar",
            cookies,
        ]
        final_url = run(
            [
                *common,
                "--location",
                "--output",
                os.devnull,
                "--write-out",
                "%{url_effective}",
                login_url,
            ]
        ).stdout
        query = urllib.parse.urlparse(final_url).query
        endpoint = f"{authentik_url}/api/v3/flows/executor/default-authentication-flow/?{query}"
        run([*common, endpoint])

        def post(payload: dict[str, str]) -> dict[str, Any]:
            result = run(
                [
                    *common,
                    "--location",
                    "--post302",
                    "--header",
                    "Content-Type: application/json",
                    "--data-binary",
                    "@-",
                    endpoint,
                ],
                input_text=json.dumps(payload),
            )
            return json.loads(result.stdout)

        identification = post({"uid_field": username})
        if identification.get("component") != "ak-stage-password":
            raise CommandError("Authentik identification did not reach the password stage")
        authenticated = post({"password": password})
        return str(authenticated.get("component", ""))


def identity_smoke(kubeconfig: Path, contract_path: Path, root_ca: Path) -> int:
    """Verify the live Authentik -> Argo CD OIDC, RBAC, and break-glass chain."""
    if not os.environ.get("BAO_TOKEN"):
        raise CommandError("BAO_TOKEN is required")
    ensure_file(root_ca, "homelab root CA")
    env = contract(contract_path)
    argocd_host = env["hosts"]["argocd"]
    authentik_host = env["hosts"]["authentik"]
    admin_group = env["identity"]["administrator"]["group"]
    issuer = f"https://{authentik_host}/application/o/argocd/"

    configmaps = json.loads(
        kubectl(
            kubeconfig,
            "-n",
            "argocd",
            "get",
            "configmap",
            "argocd-cm",
            "argocd-rbac-cm",
            "-o",
            "json",
        ).stdout
    )
    data = {item["metadata"]["name"]: item.get("data", {}) for item in configmaps["items"]}
    issues = argocd_identity_contract_issues(
        data.get("argocd-cm", {}).get("oidc.config", ""),
        data.get("argocd-rbac-cm", {}),
        issuer=issuer,
        admin_group=admin_group,
    )
    if issues:
        raise CommandError("; ".join(issues))
    print("PASS Argo CD OIDC and RBAC declarative contract")

    for namespace, names in (
        ("argocd", ("argocd-oidc",)),
        (
            "authentik",
            (
                "platform-identity-blueprint",
                "argocd-sso-blueprint",
                "harbor-sso-blueprint",
                "grafana-sso-blueprint",
            ),
        ),
    ):
        for name in names:
            payload = json.loads(
                kubectl(
                    kubeconfig,
                    "-n",
                    namespace,
                    "get",
                    "externalsecret",
                    name,
                    "-o",
                    "json",
                ).stdout
            )
            ready = any(
                condition.get("type") == "Ready" and condition.get("status") == "True"
                for condition in payload.get("status", {}).get("conditions", [])
            )
            if not ready:
                raise CommandError(f"ExternalSecret {namespace}/{name} is not Ready")
    print("PASS identity ExternalSecrets are Ready")

    callback = f"https://{argocd_host}/auth/callback"
    shell = (
        "from authentik.core.models import Application,Group;"
        "from authentik.providers.oauth2.models import OAuth2Provider;"
        "from authentik.policies.models import PolicyBinding;"
        "from authentik.blueprints.models import BlueprintInstance;"
        "a=Application.objects.get(slug='argocd');"
        f"g=Group.objects.get(name={admin_group!r});"
        "p=OAuth2Provider.objects.get(name='Argo CD');"
        "b=list(BlueprintInstance.objects.filter(name__in=['platform-identity','argocd-sso']));"
        "ok=len(b)==2 and all(str(x.status)=='successful' for x in b) "
        "and a.provider_id==p.pk and str(p.client_type)=='confidential' "
        "and PolicyBinding.objects.filter(target=a.pk,group=g,enabled=True).exists() "
        f"and any(x.url=={callback!r} and str(x.matching_mode)=='strict' for x in p.redirect_uris);"
        "print('IDENTITY_SMOKE_OK' if ok else 'IDENTITY_SMOKE_FAIL')"
    )
    model = kubectl(
        kubeconfig,
        "-n",
        "authentik",
        "exec",
        "deployment/authentik-server",
        "--",
        "ak",
        "shell",
        "-c",
        shell,
        check=False,
    )
    if model.returncode or "IDENTITY_SMOKE_OK" not in model.stdout:
        raise CommandError("Authentik Argo CD blueprint/provider binding is not healthy")
    print("PASS Authentik identity and Argo CD blueprints are successful")

    discovery_result = run(
        [
            "curl",
            "--silent",
            "--show-error",
            "--fail",
            "--cacert",
            root_ca,
            f"{issuer}.well-known/openid-configuration",
        ]
    )
    discovery = json.loads(discovery_result.stdout)
    if discovery.get("issuer") != issuer or not all(
        discovery.get(key) for key in ("authorization_endpoint", "token_endpoint", "jwks_uri")
    ):
        raise CommandError("Authentik OIDC discovery document is incomplete")
    status, location = _https_redirect(f"https://{argocd_host}/auth/login", root_ca)
    redirect = urllib.parse.urlparse(location)
    query = urllib.parse.parse_qs(redirect.query)
    if (
        status not in {302, 303, 307, 308}
        or redirect.hostname != authentik_host
        or redirect.path != "/application/o/authorize/"
        or query.get("redirect_uri") != [callback]
        or set(query.get("scope", [""])[0].split()) != {"openid", "profile", "email", "groups"}
    ):
        raise CommandError(
            "Argo CD login does not redirect to the expected Authentik authorization flow"
        )
    print("PASS OIDC discovery and Argo CD authorization redirect")

    platform_admin = (
        _bao_secret(f"{os.environ.get('BAO_KV_MOUNT', 'secret')}/platform/authentik/platform-admin")
        or {}
    )
    platform_admin_password = str(platform_admin.get("password", ""))
    if not platform_admin_password:
        raise CommandError("OpenBao platform administrator password is absent")
    auth_component = _authentik_primary_auth_component(
        f"https://{argocd_host}/auth/login",
        f"https://{authentik_host}",
        env["identity"]["administrator"]["username"],
        platform_admin_password,
        root_ca,
    )
    if auth_component == "ak-stage-authenticator-validate":
        print("PASS Authentik primary login reached the MFA challenge")
    elif auth_component in {"xak-flow-redirect", "ak-flow-redirect"}:
        print("PASS Authentik primary login reached the authorization redirect")
    else:
        raise CommandError("Authentik primary login did not reach MFA or authorization redirect")

    def rbac_can(subject: str, action: str, resource: str, subresource: str = "") -> bool:
        args = [
            "-n",
            "argocd",
            "exec",
            "deployment/argocd-server",
            "--",
            "argocd",
            "admin",
            "settings",
            "rbac",
            "can",
            subject,
            action,
            resource,
        ]
        if subresource:
            args.append(subresource)
        args.extend(["--namespace", "argocd"])
        return kubectl(kubeconfig, *args, check=False).returncode == 0

    if not rbac_can(admin_group, "delete", "applications", "platform/echo"):
        raise CommandError("administrator group does not receive role:admin")
    if rbac_can("identity-smoke-user", "delete", "applications", "platform/echo"):
        raise CommandError("non-admin subject unexpectedly receives application delete")
    if not rbac_can("identity-smoke-user", "get", "applications", "platform/echo"):
        raise CommandError("authenticated default role cannot read an application")
    if rbac_can("identity-smoke-user", "get", "clusters"):
        raise CommandError("authenticated default role unexpectedly reads cluster credentials")
    print("PASS positive and negative Argo CD RBAC evaluation")

    mount = os.environ.get("BAO_KV_MOUNT", "secret")
    stored = _bao_secret(f"{mount}/platform/argocd/admin") or {}
    password = str(stored.get("password", ""))
    if not password:
        raise CommandError("OpenBao Argo CD break-glass password is absent")
    _argocd_login(f"https://{argocd_host}", root_ca, password)
    initial = kubectl(
        kubeconfig,
        "-n",
        "argocd",
        "get",
        "secret",
        "argocd-initial-admin-secret",
        check=False,
    )
    if initial.returncode == 0:
        raise CommandError("argocd-initial-admin-secret still exists")
    print("PASS OpenBao-backed Argo CD break-glass login; bootstrap Secret is absent")
    return 0


def _harbor_curl(
    url: str,
    password: str,
    root_ca: Path,
    *,
    method: str = "GET",
    check: bool = True,
) -> Any:
    authorization = base64.b64encode(f"admin:{password}".encode()).decode()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        config = Path(handle.name)
        os.chmod(config, 0o600)
        handle.write("silent\nshow-error\nfail-with-body\n")
        handle.write(f"cacert = {json.dumps(str(root_ca))}\n")
        handle.write(f'header = "Authorization: Basic {authorization}"\n')
    try:
        return run(
            ["curl", "--config", config, "--request", method, url],
            check=check,
        )
    finally:
        config.unlink(missing_ok=True)


def harbor_smoke(kubeconfig: Path, contract_path: Path, root_ca: Path) -> int:
    """Verify Harbor components, registry push/pull, Trivy scanning, and OIDC entry."""
    if not os.environ.get("BAO_TOKEN"):
        raise CommandError("BAO_TOKEN is required")
    require("curl", "skopeo")
    ensure_file(root_ca, "homelab root CA")
    env = contract(contract_path)
    harbor_host = env["hosts"]["harbor"]
    authentik_host = env["hosts"]["authentik"]
    harbor_url = f"https://{harbor_host}"
    mount = os.environ.get("BAO_KV_MOUNT", "secret")
    runtime = _bao_secret(f"{mount}/platform/harbor/runtime") or {}
    admin_password = str(runtime.get("admin_password", ""))
    if not admin_password:
        raise CommandError("OpenBao Harbor admin password is absent")

    health = json.loads(
        run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--fail",
                "--cacert",
                root_ca,
                f"{harbor_url}/api/v2.0/health",
            ]
        ).stdout
    )
    components = {item.get("name"): item.get("status") for item in health.get("components", [])}
    expected_components = {
        "core",
        "database",
        "jobservice",
        "portal",
        "redis",
        "registry",
        "registryctl",
        "trivy",
    }
    if health.get("status") != "healthy" or any(
        components.get(name) != "healthy" for name in expected_components
    ):
        raise CommandError("Harbor health API reports an unhealthy component")
    print("PASS Harbor core, database, jobservice, portal, registry, Redis, and Trivy health")

    platform_admin_password = str(
        (_bao_secret(f"{mount}/platform/authentik/platform-admin") or {}).get("password", "")
    )
    if not platform_admin_password:
        raise CommandError("OpenBao platform administrator password is absent")
    auth_component = _authentik_primary_auth_component(
        f"{harbor_url}/c/oidc/login",
        f"https://{authentik_host}",
        env["identity"]["administrator"]["username"],
        platform_admin_password,
        root_ca,
    )
    if auth_component == "ak-stage-authenticator-validate":
        print("PASS Harbor OIDC primary login reached the MFA challenge")
    elif auth_component in {"xak-flow-redirect", "ak-flow-redirect"}:
        print("PASS Harbor OIDC primary login reached the authorization redirect")
    else:
        raise CommandError("Harbor OIDC primary login did not reach MFA or authorization redirect")

    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    repository = f"stage4-smoke-{timestamp}"
    tag = "pause-3.10"
    destination = f"docker://{harbor_host}/library/{repository}:{tag}"
    api_repository = urllib.parse.quote(repository, safe="")
    pushed = False
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        authfile = Path(handle.name)
        os.chmod(authfile, 0o600)
        json.dump(
            {
                "auths": {
                    harbor_host: {
                        "auth": base64.b64encode(f"admin:{admin_password}".encode()).decode()
                    }
                }
            },
            handle,
        )
    try:
        run(
            [
                "skopeo",
                "copy",
                "--override-os",
                "linux",
                "--override-arch",
                "amd64",
                "--dest-authfile",
                authfile,
                "--dest-cert-dir",
                root_ca.parent,
                "docker://registry.k8s.io/pause:3.10",
                destination,
            ]
        )
        pushed = True
        print("PASS Harbor registry push")
        run(
            [
                "skopeo",
                "inspect",
                "--override-os",
                "linux",
                "--override-arch",
                "amd64",
                "--authfile",
                authfile,
                "--cert-dir",
                root_ca.parent,
                destination,
            ]
        )
        print("PASS Harbor registry pull/inspect")

        artifact_url = (
            f"{harbor_url}/api/v2.0/projects/library/repositories/"
            f"{api_repository}/artifacts/{urllib.parse.quote(tag, safe='')}"
        )
        _harbor_curl(f"{artifact_url}/scan", admin_password, root_ca, method="POST")

        scan_summary: dict[str, Any] = {}

        def scan_complete() -> bool:
            nonlocal scan_summary
            artifact = json.loads(
                _harbor_curl(
                    f"{artifact_url}?with_scan_overview=true",
                    admin_password,
                    root_ca,
                ).stdout
            )
            reports = list((artifact.get("scan_overview") or {}).values())
            for report in reports:
                status = report.get("scan_status")
                if status == "Error":
                    raise CommandError("Harbor Trivy scan finished with an error")
                if status == "Success":
                    scan_summary = report.get("summary", {})
                    return True
            return False

        wait_until(scan_complete, 300, 5, "Harbor Trivy scan")
        vulnerabilities = sum(
            int(value) for value in scan_summary.values() if isinstance(value, int)
        )
        print(f"PASS Harbor Trivy scan completed; reported vulnerabilities={vulnerabilities}")
    finally:
        authfile.unlink(missing_ok=True)
        if pushed:
            cleanup = _harbor_curl(
                f"{harbor_url}/api/v2.0/projects/library/repositories/{api_repository}",
                admin_password,
                root_ca,
                method="DELETE",
                check=False,
            )
            if cleanup.returncode == 0:
                print("PASS Harbor smoke repository removed")
            else:
                print("WARN Harbor smoke repository cleanup failed")

    application = json.loads(
        kubectl(kubeconfig, "-n", "argocd", "get", "application", "harbor", "-o", "json").stdout
    )
    if (
        application.get("status", {}).get("sync", {}).get("status") != "Synced"
        or application.get("status", {}).get("health", {}).get("status") != "Healthy"
        or application.get("status", {}).get("operationState", {}).get("phase") != "Succeeded"
    ):
        raise CommandError("Harbor Application is not Synced/Healthy with a successful operation")
    print("PASS Harbor Application Synced/Healthy; latest operation Succeeded")
    return 0


def observability_smoke(kubeconfig: Path) -> int:
    """Verify OTLP -> Tempo -> Grafana and a transient webhook notification."""
    pods = json.loads(
        kubectl(
            kubeconfig,
            "-n",
            "observability",
            "get",
            "pod",
            "-l",
            "app.kubernetes.io/name=grafana",
            "-o",
            "json",
        ).stdout
    )
    grafana_pod = ""
    for item in pods.get("items", []):
        statuses = item.get("status", {}).get("containerStatuses", [])
        if (
            item.get("status", {}).get("phase") == "Running"
            and statuses
            and all(status.get("ready", False) for status in statuses)
        ):
            grafana_pod = item["metadata"]["name"]
            break
    if not grafana_pod:
        raise CommandError("no ready Grafana Pod found")

    def curl(*args: str, check: bool = True) -> Any:
        return kubectl(
            kubeconfig,
            "-n",
            "observability",
            "exec",
            grafana_pod,
            "--",
            "curl",
            "-fsS",
            "--connect-timeout",
            "5",
            "--max-time",
            "20",
            *args,
            check=check,
        )

    def grafana_api(*args: str, check: bool = True) -> Any:
        return kubectl(
            kubeconfig,
            "-n",
            "observability",
            "exec",
            grafana_pod,
            "--",
            "sh",
            "-c",
            "curl -fsS --connect-timeout 5 --max-time 20 "
            '-u "$GF_SECURITY_ADMIN_USER:$GF_SECURITY_ADMIN_PASSWORD" "$@"',
            "sh",
            *args,
            check=check,
        )

    metrics_url = "http://otel-collector.observability.svc.cluster.local:8888/metrics"
    before_metrics = curl(metrics_url).stdout
    before_sent = prometheus_metric_sum(
        before_metrics, "otelcol_exporter_sent_spans", 'exporter="otlp/tempo"'
    )
    before_failed = prometheus_metric_sum(
        before_metrics, "otelcol_exporter_send_failed_spans", 'exporter="otlp/tempo"'
    )

    trace_id = secrets.token_hex(16)
    span_id = secrets.token_hex(8)
    trace = otlp_trace_payload(trace_id, span_id, int(datetime.now(UTC).timestamp() * 1e9))
    curl(
        "-H",
        "Content-Type: application/json",
        "--data-binary",
        trace,
        "http://otel-collector.observability.svc.cluster.local:4318/v1/traces",
    )

    trace_url = f"http://127.0.0.1:3000/api/datasources/proxy/uid/tempo/api/traces/{trace_id}"
    wait_until(
        lambda: grafana_api(trace_url, check=False).returncode == 0,
        60,
        2,
        "test trace query through Grafana and Tempo",
    )
    print(f"PASS OTLP trace {trace_id} is queryable through Grafana and Tempo")

    after_metrics = curl(metrics_url).stdout
    after_sent = prometheus_metric_sum(
        after_metrics, "otelcol_exporter_sent_spans", 'exporter="otlp/tempo"'
    )
    after_failed = prometheus_metric_sum(
        after_metrics, "otelcol_exporter_send_failed_spans", 'exporter="otlp/tempo"'
    )
    queue_size = prometheus_metric_sum(
        after_metrics, "otelcol_exporter_queue_size", 'exporter="otlp/tempo"'
    )
    if after_sent <= before_sent:
        raise CommandError("Tempo exporter sent counter did not increase")
    if after_failed > before_failed or queue_size != 0:
        raise CommandError("Tempo exporter failure counter increased or sending queue is not empty")
    print("PASS Tempo exporter sent spans increased without failures or queued spans")

    dashboards = json.loads(grafana_api("http://127.0.0.1:3000/api/search?type=dash-db").stdout)
    dashboard_uids = {item.get("uid") for item in dashboards}
    required_dashboards = {
        "observability-overview",
        "otel-collector",
        "cilium-hubble",
        "velero-kyverno",
    }
    missing_dashboards = required_dashboards - dashboard_uids
    if missing_dashboards:
        raise CommandError("missing Grafana dashboards: " + ", ".join(sorted(missing_dashboards)))

    rules = json.loads(grafana_api("http://127.0.0.1:3000/api/v1/provisioning/alert-rules").stdout)
    rule_uids = {item.get("uid") for item in rules}
    required_rules = {
        "observability-target-down",
        "otel-exporter-failures",
        "otel-exporter-queue-saturation",
        "velero-storage-unavailable",
        "velero-backup-stale",
    }
    missing_rules = required_rules - rule_uids
    if missing_rules:
        raise CommandError("missing Grafana alert rules: " + ", ".join(sorted(missing_rules)))
    print("PASS Grafana dashboards and provisioned alert rules are available")

    webhook_url = "http://echo.echo.svc.cluster.local/observability-webhook-smoke"
    webhook_payload = json.dumps(
        {
            "integration": {
                "type": "webhook",
                "settings": {"url": webhook_url},
                "secureFields": {},
                "disableResolveMessage": False,
            },
            "alert": {
                "labels": {"alertname": "ObservabilityWebhookSmoke"},
                "annotations": {"summary": "Internal webhook delivery smoke test"},
            },
        },
        separators=(",", ":"),
    )
    webhook_result = json.loads(
        grafana_api(
            "-H",
            "Content-Type: application/json",
            "--data-binary",
            webhook_payload,
            "http://127.0.0.1:3000/apis/notifications.alerting.grafana.app/"
            "v1beta1/namespaces/default/receivers/-/test",
        ).stdout
    )
    if webhook_result.get("status") != "success":
        raise CommandError("Grafana webhook notification test failed")
    print("PASS Grafana webhook test notification delivered to the internal echo receiver")
    return 0


def backup_restore_smoke(kubeconfig: Path) -> int:
    """Exercise Garage -> Velero -> Kubernetes restore without reading secret values."""
    source_namespace = "echo"
    source_name = "homelab-root-ca"
    suffix = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    backup_name = f"echo-restore-smoke-{suffix}"
    restore_name = backup_name
    target_namespace = backup_name

    source = json.loads(
        kubectl(
            kubeconfig,
            "-n",
            source_namespace,
            "get",
            "configmap",
            source_name,
            "-o",
            "json",
        ).stdout
    )

    def content_digest(configmap: dict[str, Any]) -> str:
        content = {
            "data": configmap.get("data", {}),
            "binaryData": configmap.get("binaryData", {}),
        }
        encoded = json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def apply(document: dict[str, Any]) -> None:
        run(
            ["kubectl", "--kubeconfig", kubeconfig, "apply", "-f", "-"],
            input_text=json.dumps(document),
        )

    labels = {"homelab.dev/restore-smoke": "true"}
    apply(
        {
            "apiVersion": "velero.io/v1",
            "kind": "Backup",
            "metadata": {"name": backup_name, "namespace": "velero", "labels": labels},
            "spec": {
                "includedNamespaces": [source_namespace],
                "includedResources": ["configmaps"],
                "snapshotVolumes": False,
                "storageLocation": "default",
                "ttl": "168h0m0s",
            },
        }
    )

    def completed(kind: str, name: str) -> bool:
        payload = json.loads(
            kubectl(kubeconfig, "-n", "velero", "get", kind, name, "-o", "json").stdout
        )
        phase = str(payload.get("status", {}).get("phase") or "")
        if phase in {"Failed", "PartiallyFailed", "FailedValidation"}:
            raise CommandError(f"Velero {kind}/{name} finished with phase {phase}")
        return phase == "Completed"

    wait_until(lambda: completed("backup", backup_name), 600, 5, f"Backup/{backup_name}")
    print(f"PASS Velero Backup/{backup_name} completed")
    apply(
        {
            "apiVersion": "velero.io/v1",
            "kind": "Restore",
            "metadata": {"name": restore_name, "namespace": "velero", "labels": labels},
            "spec": {
                "backupName": backup_name,
                "includedNamespaces": [source_namespace],
                "includedResources": ["configmaps"],
                "namespaceMapping": {source_namespace: target_namespace},
            },
        }
    )
    wait_until(lambda: completed("restore", restore_name), 600, 5, f"Restore/{restore_name}")
    restored = json.loads(
        kubectl(
            kubeconfig,
            "-n",
            target_namespace,
            "get",
            "configmap",
            source_name,
            "-o",
            "json",
        ).stdout
    )
    if content_digest(source) != content_digest(restored):
        raise CommandError("restored ConfigMap content does not match its source")
    kubectl(
        kubeconfig,
        "-n",
        "velero",
        "label",
        "restore",
        restore_name,
        "homelab.dev/restore-verified=true",
        "--overwrite",
    )
    print(
        f"PASS Velero Restore/{restore_name} verified in namespace {target_namespace}; "
        "cleanup remains an explicit operator action"
    )
    return 0


def post_argocd_check(kubeconfig: Path, contract_path: Path) -> int:
    env = contract(contract_path)
    apps = (
        "platform",
        "apps",
        "gateway",
        "hubble",
        "authentik-prereqs",
        "authentik-postgresql",
        "authentik-redis",
        "authentik",
        "forgejo-prereqs",
        "forgejo-postgresql",
        "forgejo-valkey",
        "forgejo",
        "harbor-prereqs",
        "harbor-postgresql",
        "harbor-valkey",
        "harbor",
        "stalwart-prereqs",
        "stalwart",
        "woodpecker-prereqs",
        "woodpecker",
        "garage-prereqs",
        "garage",
        "observability-prereqs",
        "victoria-metrics",
        "loki",
        "tempo",
        "otel-collector",
        "otel-agent",
        "grafana",
        "velero-prereqs",
        "velero",
        "kyverno-prereqs",
        "kyverno",
        "kyverno-policies",
    )
    namespaces = (
        "argocd",
        "authentik",
        "forgejo",
        "gateway",
        "garage",
        "harbor",
        "stalwart",
        "kube-system",
        "observability",
        "velero",
        "woodpecker",
        "kyverno",
        "echo",
    )
    resources = (
        ("authentik", "secret", "authentik-runtime"),
        ("authentik", "secret", "platform-identity-blueprint"),
        ("forgejo", "secret", "forgejo-admin-secret"),
        ("forgejo", "secret", "forgejo-oidc"),
        ("argocd", "secret", "argocd-oidc"),
        ("harbor", "secret", "harbor-runtime"),
        ("harbor", "secret", "harbor-oidc-config"),
        ("stalwart", "secret", "stalwart-runtime"),
        ("woodpecker", "secret", "woodpecker-runtime"),
        ("garage", "secret", "garage-config"),
        ("observability", "secret", "grafana-admin-secret"),
        ("observability", "secret", "grafana-oidc"),
        ("velero", "secret", "velero-credentials"),
    )
    failures: list[str] = []

    def check(label: str, *command: str) -> None:
        if kubectl(kubeconfig, *command, check=False).returncode == 0:
            print(f"PASS {label}")
        else:
            print(f"FAIL {label}")
            failures.append(label)

    for namespace in namespaces:
        check(f"namespace {namespace}", "get", "namespace", namespace)
    root = (
        "root-ssh"
        if kubectl(
            kubeconfig, "-n", "argocd", "get", "application", "root-ssh", check=False
        ).returncode
        == 0
        else "root"
    )
    for app in (root, *apps):
        if argocd_status(kubeconfig, app, "sync") != "Synced":
            failures.append(f"{app} Synced")
        if argocd_status(kubeconfig, app, "health") != "Healthy":
            failures.append(f"{app} Healthy")

    applications_result = kubectl(
        kubeconfig,
        "-n",
        "argocd",
        "get",
        "application",
        "-o",
        "json",
        check=False,
    )
    applications_payload: dict[str, Any] = {"items": []}
    operation_issues: list[str] = []
    if applications_result.returncode == 0:
        applications_payload = json.loads(applications_result.stdout)
        operation_issues = application_operation_issues(
            applications_payload,
            {root, *apps},
        )
    else:
        operation_issues.append("unable to list Argo CD Applications")
    if operation_issues:
        for issue in operation_issues:
            print(f"FAIL Argo CD operation {issue}")
        failures.append("Argo CD operations completed")
    else:
        print("PASS Argo CD operations completed")

    pods_result = kubectl(kubeconfig, "get", "pod", "-A", "-o", "json", check=False)
    pod_issues: list[str] = []
    if pods_result.returncode == 0:
        pod_issues = pod_readiness_issues(json.loads(pods_result.stdout), set(namespaces))
    else:
        pod_issues.append("unable to list Pods")
    if pod_issues:
        for issue in pod_issues:
            print(f"FAIL Pod readiness {issue}")
        failures.append("runtime Pods ready")
    else:
        print("PASS runtime Pods ready")

    for namespace, kind, name in resources:
        check(f"{namespace}/{kind}/{name}", "-n", namespace, "get", kind, name)
    check("ClusterSecretStore/openbao", "get", "clustersecretstore", "openbao")
    for namespace, workload, name in (
        ("authentik", "deployment", "authentik-server"),
        ("forgejo", "deployment", "forgejo"),
        ("harbor", "deployment", "harbor-core"),
        ("stalwart", "statefulset", "stalwart"),
        ("woodpecker", "statefulset", "woodpecker-server"),
        ("garage", "statefulset", "garage"),
        ("observability", "statefulset", "tempo"),
        ("velero", "deployment", "velero"),
    ):
        check(
            f"rollout {namespace}/{name}",
            "-n",
            namespace,
            "rollout",
            "status",
            f"{workload}/{name}",
            "--timeout=240s",
        )

    tempo_pvc_phase = kubectl(
        kubeconfig,
        "-n",
        env["platform"]["observability"]["namespace"],
        "get",
        "pvc",
        "storage-tempo-0",
        "-o",
        "jsonpath={.status.phase}",
        check=False,
    ).stdout.strip()
    if tempo_pvc_phase == "Bound":
        print("PASS Tempo PVC storage-tempo-0 Bound")
    else:
        print("FAIL Tempo PVC storage-tempo-0 is not Bound")
        failures.append("Tempo PVC Bound")

    bsl_phase = kubectl(
        kubeconfig,
        "-n",
        "velero",
        "get",
        "backupstoragelocation",
        "default",
        "-o",
        "jsonpath={.status.phase}",
        check=False,
    ).stdout.strip()
    if bsl_phase == "Available":
        print("PASS velero BackupStorageLocation/default Available")
    else:
        print("FAIL velero BackupStorageLocation/default Available")
        failures.append("velero BSL Available")

    backups_result = kubectl(kubeconfig, "-n", "velero", "get", "backup", "-o", "json", check=False)
    latest_backup: tuple[str, float] | None = None
    if backups_result.returncode == 0:
        latest_backup = latest_completed_backup_age_hours(json.loads(backups_result.stdout))
    max_backup_age_hours = float(os.environ.get("POST_CHECK_MAX_BACKUP_AGE_HOURS", "3"))
    if latest_backup and latest_backup[1] <= max_backup_age_hours:
        print(f"PASS velero latest completed Backup {latest_backup[0]} age={latest_backup[1]:.2f}h")
    else:
        print(f"FAIL velero has no completed Backup newer than {max_backup_age_hours:g}h")
        failures.append("velero fresh completed Backup")

    restores_result = kubectl(
        kubeconfig,
        "-n",
        "velero",
        "get",
        "restore",
        "-l",
        "homelab.dev/restore-smoke=true,homelab.dev/restore-verified=true",
        "-o",
        "json",
        check=False,
    )
    latest_restore: tuple[str, float] | None = None
    if restores_result.returncode == 0:
        latest_restore = latest_completed_restore_age_hours(json.loads(restores_result.stdout))
    max_restore_age_hours = float(os.environ.get("POST_CHECK_MAX_RESTORE_AGE_HOURS", "168"))
    if latest_restore and latest_restore[1] <= max_restore_age_hours:
        print(
            f"PASS velero latest verified Restore {latest_restore[0]} age={latest_restore[1]:.2f}h"
        )
    else:
        print(f"FAIL velero has no verified Restore newer than {max_restore_age_hours:g}h")
        failures.append("velero fresh verified Restore")

    garage_status = kubectl(
        kubeconfig, "-n", "garage", "exec", "garage-0", "--", "/garage", "status", check=False
    )
    if garage_status.returncode == 0 and "NO ROLE ASSIGNED" not in garage_status.stdout:
        print("PASS Garage layout assigned")
    else:
        print("FAIL Garage layout assigned")
        failures.append("Garage layout")

    garage_bucket = str(env["platform"]["velero"]["bucket"])
    garage_buckets = kubectl(
        kubeconfig,
        "-n",
        env["platform"]["garage"]["namespace"],
        "exec",
        "garage-0",
        "--",
        "/garage",
        "bucket",
        "list",
        check=False,
    )
    if garage_buckets.returncode == 0 and re.search(
        rf"(?m)(?:^|\s){re.escape(garage_bucket)}(?:\s|$)", garage_buckets.stdout
    ):
        print(f"PASS Garage bucket {garage_bucket} exists")
    else:
        print(f"FAIL Garage bucket {garage_bucket} is not ready")
        failures.append("Garage bucket")

    identity_configmaps = kubectl(
        kubeconfig,
        "-n",
        "argocd",
        "get",
        "configmap",
        "argocd-cm",
        "argocd-rbac-cm",
        "-o",
        "json",
        check=False,
    )
    identity_issues: list[str] = []
    if identity_configmaps.returncode == 0:
        identity_data = {
            item.get("metadata", {}).get("name"): item.get("data", {})
            for item in json.loads(identity_configmaps.stdout).get("items", [])
        }
        identity_issues = argocd_identity_contract_issues(
            identity_data.get("argocd-cm", {}).get("oidc.config", ""),
            identity_data.get("argocd-rbac-cm", {}),
            issuer=f"https://{env['hosts']['authentik']}/application/o/argocd/",
            admin_group=env["identity"]["administrator"]["group"],
        )
    else:
        identity_issues.append("unable to read Argo CD identity ConfigMaps")
    if identity_issues:
        for issue in identity_issues:
            print(f"FAIL Argo CD identity contract: {issue}")
        failures.append("Argo CD OIDC/RBAC contract")
    else:
        print("PASS Argo CD OIDC/RBAC contract")

    initial_admin = kubectl(
        kubeconfig,
        "-n",
        "argocd",
        "get",
        "secret",
        "argocd-initial-admin-secret",
        "--ignore-not-found",
        "-o",
        "name",
        check=False,
    )
    if initial_admin.returncode == 0 and not initial_admin.stdout.strip():
        print("PASS Argo CD bootstrap admin Secret is absent")
    else:
        print("FAIL Argo CD bootstrap admin Secret still exists or cannot be checked")
        failures.append("Argo CD bootstrap Secret lifecycle")

    policy_reports = kubectl(
        kubeconfig,
        "get",
        "policyreport,clusterpolicyreport",
        "-A",
        "-o",
        "json",
        check=False,
    )
    policy_issues: list[str] = []
    used_policy_exceptions: set[str] = set()
    if policy_reports.returncode == 0:
        policy_issues, used_policy_exceptions = kyverno_policy_report_issues(
            json.loads(policy_reports.stdout),
            load_kyverno_allowlist(ROOT / "argocd/audit/kyverno-policy-allowlist.yaml"),
        )
    else:
        policy_issues.append("unable to list PolicyReports")
    if not policy_issues:
        suffix = (
            f"; accepted exceptions={len(used_policy_exceptions)}" if used_policy_exceptions else ""
        )
        print(f"PASS Kyverno PolicyReports have no unexplained violations{suffix}")
    else:
        for issue in policy_issues:
            print(f"FAIL Kyverno PolicyReport {issue}")
        failures.append("Kyverno PolicyReports")

    collector_logs = kubectl(
        kubeconfig,
        "-n",
        "observability",
        "logs",
        "deployment/otel-collector",
        "--since=2m",
        "--tail=5000",
        check=False,
    )
    agent_logs = kubectl(
        kubeconfig,
        "-n",
        "observability",
        "logs",
        "-l",
        "app.kubernetes.io/instance=otel-agent",
        "--all-containers=true",
        "--prefix=true",
        "--max-log-requests=20",
        "--since=2m",
        "--tail=5000",
        check=False,
    )
    telemetry_errors = 0
    if collector_logs.returncode == 0 and agent_logs.returncode == 0:
        telemetry_errors = telemetry_log_error_count(collector_logs.stdout)
        telemetry_errors += telemetry_log_error_count(agent_logs.stdout)
    else:
        telemetry_errors = -1
    if telemetry_errors == 0:
        print("PASS OpenTelemetry has no recent scrape/export errors")
    elif telemetry_errors < 0:
        print("FAIL unable to inspect recent OpenTelemetry logs")
        failures.append("OpenTelemetry logs available")
    else:
        print(f"FAIL OpenTelemetry has {telemetry_errors} recent scrape/export errors")
        failures.append("OpenTelemetry recent errors")

    try:
        observability_smoke(kubeconfig)
    except CommandError as exc:
        print(f"FAIL observability synthetic round-trip: {exc}")
        failures.append("Tempo synthetic trace and OTel exporter counters")

    expected_revision = os.environ.get("EXPECTED_GITOPS_REVISION", "").strip()
    if not expected_revision:
        expected_revision = run(["git", "rev-parse", "HEAD"], cwd=ROOT).stdout.strip()
    critical_apps = {
        "authentik-prereqs",
        "authentik-postgresql",
        "authentik-redis",
        "authentik",
        "garage-prereqs",
        "garage",
        "velero-prereqs",
        "velero",
        "kyverno-prereqs",
        "kyverno",
        "kyverno-policies",
    }
    revision_issues = application_revision_issues(
        applications_payload,
        root=root,
        expected_revision=expected_revision,
        critical_apps=critical_apps,
        critical_revision=env["gitops"]["critical_revision"],
    )
    if revision_issues:
        for issue in revision_issues:
            print(f"FAIL GitOps revision: {issue}")
        failures.append("GitOps expected revisions")
    else:
        print(f"PASS GitOps root snapshot {expected_revision} and critical revisions")
    if failures:
        raise CommandError("post-Argo CD checks failed: " + ", ".join(failures))
    print("PASS post-deploy checks completed")
    return 0


def destroy_infrastructure(extra: list[str]) -> int:
    infra = ROOT / "infrastructure"
    cluster = ROOT / "cluster"
    env = os.environ.copy()
    kube = run(
        ["tofu", f"-chdir={cluster}", "output", "-raw", "kubeconfig_path"], check=False
    ).stdout.strip()
    if kube and Path(kube).is_file():
        env["KUBECONFIG"] = kube
    pairs = (
        ("kubernetes_manifest.selfsigned_clusterissuer[0]", "clusterissuers.cert-manager.io"),
        ("kubernetes_manifest.homelab_root_ca[0]", "certificates.cert-manager.io"),
        ("kubernetes_manifest.homelab_ca_clusterissuer[0]", "clusterissuers.cert-manager.io"),
        ("kubernetes_manifest.homelab_trust_bundle[0]", "bundles.trust.cert-manager.io"),
        (
            "kubernetes_manifest.linstor_satellite_configuration_talos[0]",
            "linstorsatelliteconfigurations.piraeus.io",
        ),
        ("kubernetes_manifest.linstor_cluster[0]", "linstorclusters.piraeus.io"),
    )
    present = []
    for target, crd in pairs:
        if run(["tofu", f"-chdir={infra}", "state", "list", target], check=False).returncode == 0:
            if (
                kube
                and run(
                    ["kubectl", "--kubeconfig", kube, "get", "crd", crd], check=False
                ).returncode
                != 0
            ):
                run(["tofu", f"-chdir={infra}", "state", "rm", target])
            else:
                present.append(target)
    if present:
        run(
            [
                "tofu",
                f"-chdir={infra}",
                "destroy",
                "-refresh=false",
                *extra,
                *[f"-target={x}" for x in present],
            ],
            capture=False,
        )
    run(["tofu", f"-chdir={infra}", "destroy", "-refresh=false", *extra], capture=False)
    return 0
