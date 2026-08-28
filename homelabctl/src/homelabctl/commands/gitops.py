from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from homelabctl.commands.operations import (
    argocd_apply,
    bao_temp_put,
    contract,
    kubectl,
    wait_argocd,
)
from homelabctl.project import ROOT
from homelabctl.runtime import CommandError, require, run, wait_until


def require_clean_argocd() -> None:
    checks = (
        ["git", "diff", "--quiet", "--", "argocd"],
        ["git", "diff", "--cached", "--quiet", "--", "argocd"],
    )
    if any(run(cmd, cwd=ROOT, check=False).returncode for cmd in checks):
        raise CommandError("argocd/ has uncommitted changes; commit them before publishing")
    if run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "argocd"], cwd=ROOT
    ).stdout.strip():
        raise CommandError("argocd/ has untracked files; commit them before publishing")


def forgejo_connection(kubeconfig: Path, env: dict[str, Any]) -> tuple[str, str, str, str, str]:
    forgejo = env["platform"]["forgejo"]
    namespace = forgejo["namespace"]
    host = env["hosts"]["forgejo"]
    ip = kubectl(
        kubeconfig,
        "-n",
        namespace,
        "get",
        "service",
        "cilium-gateway-forgejo",
        "-o",
        "jsonpath={.status.loadBalancer.ingress[0].ip}",
    ).stdout.strip()
    secret_name = kubectl(
        kubeconfig,
        "-n",
        namespace,
        "get",
        "gateway",
        "forgejo",
        "-o",
        'jsonpath={.spec.listeners[?(@.protocol=="HTTPS")].tls.certificateRefs[0].name}',
    ).stdout.strip()
    secret = json.loads(
        kubectl(
            kubeconfig, "-n", namespace, "get", "secret", forgejo["admin_secret_name"], "-o", "json"
        ).stdout
    )["data"]
    user = base64.b64decode(secret["username"]).decode()
    password = base64.b64decode(secret["password"]).decode()
    cert = base64.b64decode(
        json.loads(
            kubectl(kubeconfig, "-n", namespace, "get", "secret", secret_name, "-o", "json").stdout
        )["data"]["tls.crt"]
    ).decode()
    return host, ip, user, password, cert


def push_subtree(
    repo_url: str, revision: str, host: str, ip: str, user: str, password: str, ca: Path
) -> None:
    commit = run(["git", "subtree", "split", "--prefix=argocd", "HEAD"], cwd=ROOT).stdout.strip()
    askpass = shutil.which("homelabctl-forgejo-askpass")
    if not askpass:
        raise CommandError("homelabctl-forgejo-askpass entrypoint is unavailable")
    env = {
        "GIT_ASKPASS": askpass,
        "GIT_TERMINAL_PROMPT": "0",
        "FORGEJO_GIT_USERNAME": user,
        "FORGEJO_GIT_PASSWORD": password,
    }
    run(
        [
            "git",
            "-c",
            "credential.helper=",
            "-c",
            f"http.sslCAInfo={ca}",
            "-c",
            f"http.curloptResolve={host}:443:{ip}",
            "push",
            repo_url,
            f"{commit}:refs/heads/{revision}",
        ],
        cwd=ROOT,
        env=env,
        capture=False,
    )


def push(kubeconfig: Path, contract_path: Path) -> int:
    require("git", "kubectl")
    env = contract(contract_path)
    require_clean_argocd()
    repo = env["gitops"]["repo_url"]
    revision = env["gitops"]["revision"]
    host, ip, user, password, cert = forgejo_connection(kubeconfig, env)
    if not repo.startswith(f"https://{host}/") or not repo.endswith(".git"):
        raise CommandError("gitops.repo_url must be an HTTPS Forgejo URL")
    with tempfile.NamedTemporaryFile("w", delete=False) as handle:
        ca = Path(handle.name)
        handle.write(cert)
    try:
        push_subtree(repo, revision, host, ip, user, password, ca)
    finally:
        ca.unlink(missing_ok=True)
    return 0


def test_ssh_bootstrap(kubeconfig: Path, hostname: str, port: int, timeout: int) -> int:
    if hostname.startswith(("localhost", "127.")) or hostname in {"::1", "git.localtest.me"}:
        raise CommandError("test SSH Git hostname must be reachable from Argo CD pods")
    env = {
        "TEST_SSH_GIT_HOSTNAME": hostname,
        "TEST_SSH_GIT_PORT": str(port),
        "SERVER_PORT": str(port),
    }
    run([str(ROOT / "test-ssh-git/setup.sh")], env=env, capture=False)
    compose = [
        "docker",
        "compose",
        "--project-directory",
        ROOT / "test-ssh-git",
        "-f",
        ROOT / "test-ssh-git/docker-compose.yaml",
    ]
    buildx = run(["docker", "buildx", "version"], check=False).returncode == 0
    run([*compose, "up", "-d", "--build" if buildx else "--no-build"], env=env, capture=False)
    repo = f"ssh://git@{hostname}:{port}/home/git/repos/gitops.git"
    key = ROOT / "test-ssh-git/keys/argocd_test_client_ed25519"
    known = ROOT / "test-ssh-git/keys/known_hosts"
    ssh = (
        f"ssh -i {key} -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile={known}"
    )
    wait_until(
        lambda: (
            run(["git", "ls-remote", repo], env={"GIT_SSH_COMMAND": ssh}, check=False).returncode
            == 0
        ),
        120,
        2,
        "test SSH repository",
    )
    return argocd_apply(kubeconfig, ROOT / "argocd/bootstrap/root-application.yaml", timeout, True)


class ForgejoApi:
    def __init__(self, host: str, ip: str, ca: Path, admin: tuple[str, str]):
        self.host = host
        self.ip = ip
        self.ca = ca
        self.admin = admin

    def call(
        self,
        method: str,
        path: str,
        *,
        auth: tuple[str, str] | None = None,
        token: str | None = None,
        data: Any = None,
    ) -> tuple[int, Any]:
        with (
            tempfile.NamedTemporaryFile("w", delete=False) as cfg,
            tempfile.NamedTemporaryFile("w", delete=False) as body,
        ):
            cfg_path = Path(cfg.name)
            body_path = Path(body.name)
            os.chmod(cfg_path, 0o600)
            cfg.write(
                f'silent\nshow-error\ncacert = "{self.ca}"\nresolve = "{self.host}:443:{self.ip}"\n'
            )
            if auth:
                cfg.write(f'user = "{auth[0]}:{auth[1]}"\n')
            if token:
                cfg.write(f'header = "Authorization: token {token}"\n')
            if data is not None:
                cfg.write('header = "Content-Type: application/json"\n')
        try:
            args = [
                "curl",
                "--config",
                cfg_path,
                "--request",
                method,
                "--output",
                body_path,
                "--write-out",
                "%{http_code}",
            ]
            input_text = None
            if data is not None:
                args += ["--data-binary", "@-"]
                input_text = json.dumps(data, separators=(",", ":"))
            result = run([*args, f"https://{self.host}/api/v1{path}"], input_text=input_text)
            raw = body_path.read_text()
            payload = json.loads(raw) if raw.strip() else None
            return int(result.stdout), payload
        finally:
            cfg_path.unlink(missing_ok=True)
            body_path.unlink(missing_ok=True)


def cutover(kubeconfig: Path, contract_path: Path, timeout: int) -> int:
    require("bao", "curl", "docker", "git", "kubectl")
    if not os.environ.get("BAO_TOKEN"):
        raise CommandError("BAO_TOKEN is required")
    env = contract(contract_path)
    require_clean_argocd()
    repo = env["gitops"]["repo_url"]
    if env["gitops"]["revision"] != "main":
        raise CommandError("cutover requires gitops.revision=main")
    host, ip, admin, password, cert = forgejo_connection(kubeconfig, env)
    parts = repo.removeprefix(f"https://{host}/").removesuffix(".git").split("/")
    if len(parts) != 2:
        raise CommandError("gitops.repo_url must contain organization/repository")
    org, name = parts
    with tempfile.NamedTemporaryFile("w", delete=False) as handle:
        ca = Path(handle.name)
        handle.write(cert)
    try:
        api = ForgejoApi(host, ip, ca, (admin, password))
        status, _ = api.call("GET", f"/orgs/{org}", auth=(admin, password))
        if status == 404:
            status, _ = api.call(
                "POST",
                f"/admin/users/{admin}/orgs",
                auth=(admin, password),
                data={"username": org, "visibility": "private"},
            )
        if status not in {200, 201}:
            raise CommandError(f"Forgejo organization request failed: {status}")
        status, _ = api.call("GET", f"/repos/{org}/{name}", auth=(admin, password))
        if status == 404:
            status, _ = api.call(
                "POST",
                f"/orgs/{org}/repos",
                auth=(admin, password),
                data={"name": name, "private": True, "auto_init": False, "default_branch": "main"},
            )
        if status not in {200, 201}:
            raise CommandError(f"Forgejo repository request failed: {status}")
        service_user = "argocd"
        service_password = secrets_token()
        status, _ = api.call("GET", f"/users/{service_user}", auth=(admin, password))
        if status == 404:
            status, _ = api.call(
                "POST",
                "/admin/users",
                auth=(admin, password),
                data={
                    "username": service_user,
                    "email": f"argocd@{host}",
                    "password": service_password,
                    "must_change_password": False,
                    "restricted": True,
                    "send_notify": False,
                },
            )
        if status not in {200, 201}:
            raise CommandError(f"Forgejo service user request failed: {status}")
        api.call(
            "PUT",
            f"/repos/{org}/{name}/collaborators/{service_user}",
            auth=(admin, password),
            data={"permission": "read"},
        )
        stored = run(
            ["bao", "kv", "get", "-format=json", "secret/platform/argocd/repository"], check=False
        )
        token = ""
        if stored.returncode == 0:
            token = str(json.loads(stored.stdout).get("data", {}).get("data", {}).get("token", ""))
        token_status, _ = (
            api.call("GET", f"/repos/{org}/{name}", token=token) if token else (0, None)
        )
        if token_status != 200:
            api.call(
                "PATCH",
                f"/admin/users/{service_user}",
                auth=(admin, password),
                data={
                    "password": service_password,
                    "must_change_password": False,
                    "restricted": True,
                },
            )
            api.call(
                "DELETE",
                f"/users/{service_user}/tokens/argocd-gitops",
                auth=(service_user, service_password),
            )
            status, payload = api.call(
                "POST",
                f"/users/{service_user}/tokens",
                auth=(service_user, service_password),
                data={
                    "name": "argocd-gitops",
                    "scopes": ["read:repository"],
                    "repositories": [{"owner": org, "name": name}],
                },
            )
            if status != 201 or not payload or not payload.get("sha1"):
                raise CommandError("cannot create Forgejo repository token")
            token = payload["sha1"]
            bao_temp_put(
                "secret/platform/argocd/repository", {"username": service_user, "token": token}
            )
        push_subtree(repo, "main", host, ip, admin, password, ca)
        ca_manifest = json.dumps({"data": {host: cert}})
        if (
            kubectl(
                kubeconfig, "-n", "argocd", "get", "configmap", "argocd-tls-certs-cm", check=False
            ).returncode
            != 0
        ):
            kubectl(kubeconfig, "-n", "argocd", "create", "configmap", "argocd-tls-certs-cm")
        kubectl(
            kubeconfig,
            "-n",
            "argocd",
            "patch",
            "configmap",
            "argocd-tls-certs-cm",
            "--type=merge",
            "-p",
            ca_manifest,
        )
        kubectl(kubeconfig, "-n", "argocd", "rollout", "restart", "deployment/argocd-repo-server")
        kubectl(
            kubeconfig,
            "-n",
            "argocd",
            "rollout",
            "status",
            "deployment/argocd-repo-server",
            f"--timeout={timeout}s",
        )
        kubectl(
            kubeconfig,
            "apply",
            "-f",
            str(ROOT / "argocd/bootstrap/projects/bootstrap.yaml"),
        )
        kubectl(
            kubeconfig,
            "apply",
            "-f",
            str(ROOT / "argocd/bootstrap/argocd-repo-server-forgejo-networkpolicy.yaml"),
        )
        kubectl(
            kubeconfig, "apply", "-f", str(ROOT / "argocd/bootstrap/forgejo-gitops-repository.yaml")
        )
        kubectl(
            kubeconfig,
            "-n",
            "argocd",
            "wait",
            "--for=condition=Ready",
            "externalsecret/forgejo-gitops-repository",
            f"--timeout={timeout}s",
        )
        if (
            kubectl(
                kubeconfig, "-n", "argocd", "get", "application", "root-ssh", check=False
            ).returncode
            == 0
        ):
            patch = json.dumps([{"op": "replace", "path": "/spec/source/repoURL", "value": repo}])
            kubectl(
                kubeconfig,
                "-n",
                "argocd",
                "patch",
                "application",
                "root-ssh",
                "--type=json",
                "-p",
                patch,
            )
            wait_argocd(kubeconfig, "root-ssh", timeout)
        argocd_apply(kubeconfig, ROOT / "argocd/bootstrap/root-application.yaml", timeout, False)
        kubectl(
            kubeconfig, "-n", "argocd", "delete", "application", "root-ssh", "--ignore-not-found"
        )
        kubectl(
            kubeconfig,
            "-n",
            "argocd",
            "delete",
            "secret",
            "test-ssh-gitops-repo",
            "--ignore-not-found",
        )
        return 0
    finally:
        ca.unlink(missing_ok=True)


def secrets_token() -> str:
    import secrets

    return secrets.token_urlsafe(48)
