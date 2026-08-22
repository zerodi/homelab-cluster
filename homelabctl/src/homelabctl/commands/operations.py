from __future__ import annotations

import base64
import json
import os
import re
import secrets
import shlex
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import bcrypt

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
            base64.b64decode(encoded).decode() if encoded else "<bootstrap secret unavailable>",
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


def post_argocd_check(kubeconfig: Path) -> int:
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
    completed_backup = False
    if backups_result.returncode == 0:
        completed_backup = any(
            item.get("status", {}).get("phase") == "Completed"
            for item in json.loads(backups_result.stdout).get("items", [])
        )
    if completed_backup:
        print("PASS velero has a completed Backup")
    else:
        print("FAIL velero has a completed Backup")
        failures.append("velero completed Backup")

    garage_status = kubectl(
        kubeconfig, "-n", "garage", "exec", "garage-0", "--", "/garage", "status", check=False
    )
    if garage_status.returncode == 0 and "NO ROLE ASSIGNED" not in garage_status.stdout:
        print("PASS Garage layout assigned")
    else:
        print("FAIL Garage layout assigned")
        failures.append("Garage layout")

    oidc_config = kubectl(
        kubeconfig,
        "-n",
        "argocd",
        "get",
        "configmap",
        "argocd-cm",
        "-o",
        "jsonpath={.data.oidc\\.config}",
        check=False,
    ).stdout.strip()
    if oidc_config:
        print("PASS Argo CD OIDC configured")
    else:
        print("FAIL Argo CD OIDC configured")
        failures.append("Argo CD OIDC")

    rbac_policy = kubectl(
        kubeconfig,
        "-n",
        "argocd",
        "get",
        "configmap",
        "argocd-rbac-cm",
        "-o",
        "jsonpath={.data.policy\\.csv}",
        check=False,
    ).stdout.strip()
    if rbac_policy:
        print("PASS Argo CD RBAC policy configured")
    else:
        print("FAIL Argo CD RBAC policy configured")
        failures.append("Argo CD RBAC")

    policy_reports = kubectl(kubeconfig, "get", "policyreport", "-A", "-o", "json", check=False)
    policy_failures = 0
    if policy_reports.returncode == 0:
        policy_failures = sum(
            int(item.get("summary", {}).get("fail", 0))
            for item in json.loads(policy_reports.stdout).get("items", [])
        )
    if policy_failures == 0:
        print("PASS Kyverno PolicyReports have no failures")
    else:
        print(f"FAIL Kyverno PolicyReports have {policy_failures} failures")
        failures.append("Kyverno PolicyReports")

    expected_revision = os.environ.get("EXPECTED_GITOPS_REVISION", "").strip()
    if expected_revision:
        live_revision = kubectl(
            kubeconfig,
            "-n",
            "argocd",
            "get",
            "application",
            root,
            "-o",
            "jsonpath={.status.sync.revision}",
            check=False,
        ).stdout.strip()
        if live_revision == expected_revision:
            print(f"PASS GitOps revision {expected_revision}")
        else:
            print("FAIL GitOps revision does not match EXPECTED_GITOPS_REVISION")
            failures.append("GitOps revision")
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
