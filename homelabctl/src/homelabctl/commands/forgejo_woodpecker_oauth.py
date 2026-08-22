# Bootstrap role: deploy (explicit operator action for Forgejo OAuth2).

from __future__ import annotations

import argparse
import base64
import html
import http.cookiejar
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from homelabctl.yamlutil import load

APPLICATION_NAME = "Woodpecker CI"
ADMIN_APPLICATIONS_PATH = "/admin/applications"
OPENBAO_PATH = "platform/woodpecker/runtime"


def run(
    args: list[str],
    *,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
    )


def require_command(name: str) -> None:
    result = run(["sh", "-c", f"command -v {name}"], check=False)
    if result.returncode != 0:
        raise RuntimeError(f"required command is missing: {name}")


def load_contract(path: Path) -> dict[str, Any]:
    contract = load(path)
    if not isinstance(contract, dict):
        raise TypeError("effective environment contract must be a mapping")
    return contract


def kubectl(args: argparse.Namespace, *command: str) -> subprocess.CompletedProcess[str]:
    return run(["kubectl", "--kubeconfig", str(args.kubeconfig), *command])


def get_kubernetes_secret(
    args: argparse.Namespace,
    namespace: str,
    name: str,
) -> dict[str, str]:
    result = kubectl(args, "-n", namespace, "get", "secret", name, "-o", "json")
    payload = json.loads(result.stdout)
    return {
        key: base64.b64decode(value).decode("utf-8")
        for key, value in payload.get("data", {}).items()
    }


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[dict[str, str]] = []
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "input":
            self.inputs.append(values)
        if tag == "meta":
            self.inputs.append(values)
        if tag == "a" and values.get("href"):
            self._href = values["href"]
            self._link_text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._link_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._link_text).strip()))
            self._href = None
            self._link_text = []


def parse_page(body: str) -> PageParser:
    parser = PageParser()
    parser.feed(body)
    return parser


def csrf_token(body: str, *, required: bool = True) -> str | None:
    for field in parse_page(body).inputs:
        if field.get("name") == "_csrf":
            value = field.get("value") or field.get("content")
            if value:
                return value
    if required:
        raise RuntimeError("Forgejo page did not contain a CSRF token")
    return None


def add_optional_csrf(fields: dict[str, str], body: str) -> dict[str, str]:
    token = csrf_token(body, required=False)
    if token:
        fields["_csrf"] = token
    return fields


def oauth_application_id(body: str, expected_name: str) -> str | None:
    for href, text in parse_page(body).links:
        match = re.search(
            r"/admin/(?:settings/)?applications/oauth2/(\d+)(?:$|[/?#])",
            href,
        )
        if match and text.casefold() == expected_name.casefold():
            return match.group(1)
    for match in re.finditer(
        r'href=["\'](/admin/(?:settings/)?applications/oauth2/(\d+))["\']',
        body,
        flags=re.IGNORECASE,
    ):
        item_start = body.rfind('class="flex-item tw-items-center"', 0, match.start())
        item_html = body[max(item_start, 0) : match.start()]
        item_text = html.unescape(re.sub(r"<[^>]+>", " ", item_html))
        if expected_name.casefold() in item_text.casefold():
            return match.group(2)
    return None


def credential_from_page(body: str, kind: str) -> str | None:
    aliases = {
        "client_id": ("client-id", "client_id", "clientid", "oauth2-client-id"),
        "client_secret": (
            "client-secret",
            "client_secret",
            "clientsecret",
            "oauth2-client-secret",
        ),
    }[kind]
    for field in parse_page(body).inputs:
        marker = " ".join((field.get("id", ""), field.get("name", ""))).casefold()
        if any(alias in marker for alias in aliases) and field.get("value"):
            return html.unescape(field["value"])

    label = r"client[ _-]?id" if kind == "client_id" else r"client[ _-]?secret"
    patterns = (
        rf"(?is){label}.{{0,500}}?value=[\"']([^\"']+)[\"']",
        rf"(?is){label}.{{0,300}}?<code[^>]*>([^<]+)</code>",
    )
    for pattern in patterns:
        match = re.search(pattern, body)
        if match:
            return html.unescape(match.group(1).strip())
    return None


class ForgejoSession:
    def __init__(self, base_url: str, ca_pem: str) -> None:
        context = ssl.create_default_context(cadata=ca_pem)
        cookies = http.cookiejar.CookieJar()
        self.base_url = base_url.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookies),
            urllib.request.HTTPSHandler(context=context),
        )

    def request(
        self,
        path: str,
        fields: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        data = None
        if fields is not None:
            data = urllib.parse.urlencode(fields).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"User-Agent": "talos-proxmox-no-ssh-operator/1"},
        )
        with self.opener.open(request, timeout=30) as response:
            return response.geturl(), response.read().decode("utf-8", errors="replace")


def authenticate(session: ForgejoSession, username: str, password: str) -> str:
    _, login_page = session.request("/user/login")
    fields = add_optional_csrf(
        {"user_name": username, "password": password},
        login_page,
    )
    session.request("/user/login", fields)
    final_url, applications = session.request(ADMIN_APPLICATIONS_PATH)
    if "/user/login" in final_url:
        raise RuntimeError("Forgejo administrator authentication failed")
    return applications


def create_or_rotate_application(
    session: ForgejoSession,
    applications_page: str,
    callback_url: str,
    rotate: bool,
) -> tuple[str, str, bool]:
    application_id = oauth_application_id(applications_page, APPLICATION_NAME)
    if application_id and not rotate:
        _, detail = session.request(f"{ADMIN_APPLICATIONS_PATH}/oauth2/{application_id}")
        client_id = credential_from_page(detail, "client_id")
        if client_id:
            return client_id, "", False
        raise RuntimeError(
            "Woodpecker CI already exists, but its client ID could not be read; "
            "inspect Forgejo and rerun with --rotate only if rotation is intended"
        )

    if application_id:
        path = f"{ADMIN_APPLICATIONS_PATH}/oauth2/{application_id}"
        _, detail = session.request(path)
        _, result = session.request(
            f"{path}/regenerate_secret",
            add_optional_csrf({}, detail),
        )
    else:
        _, result = session.request(
            f"{ADMIN_APPLICATIONS_PATH}/oauth2",
            add_optional_csrf(
                {
                    "application_name": APPLICATION_NAME,
                    "redirect_uris": callback_url,
                    "confidential_client": "on",
                },
                applications_page,
            ),
        )

    client_id = credential_from_page(result, "client_id")
    client_secret = credential_from_page(result, "client_secret")
    if not client_id or not client_secret:
        raise RuntimeError(
            "Forgejo created or rotated the OAuth2 application, but the returned "
            "credentials could not be parsed; rerun with --rotate after inspecting "
            "the system-wide application"
        )
    return client_id, client_secret, True


def read_openbao(path: str) -> tuple[dict[str, Any], int]:
    result = run(["bao", "kv", "get", "-format=json", path])
    payload = json.loads(result.stdout)
    envelope = payload.get("data", {})
    data = envelope.get("data")
    version = envelope.get("metadata", {}).get("version")
    if not isinstance(data, dict):
        raise TypeError(f"OpenBao path has no KV v2 data: {path}")
    if not isinstance(version, int):
        raise TypeError(f"OpenBao path has no KV v2 version: {path}")
    return data, version


def write_openbao(path: str, data: dict[str, Any], version: int) -> None:
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="woodpecker-oauth-",
            suffix=".json",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            os.chmod(temporary_path, 0o600)
            json.dump(data, handle, separators=(",", ":"))
        result = run(
            ["bao", "kv", "put", f"-cas={version}", path, f"@{temporary_path}"],
            check=False,
        )
    finally:
        if temporary_path:
            Path(temporary_path).unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "OpenBao write failed")


def reconcile_woodpecker(
    args: argparse.Namespace,
    namespace: str,
    external_secret: str,
    client_id: str,
    client_secret: str,
) -> None:
    kubectl(
        args,
        "-n",
        namespace,
        "annotate",
        "externalsecret",
        external_secret,
        f"force-sync={int(time.time())}",
        "--overwrite",
    )
    for _ in range(24):
        materialized = get_kubernetes_secret(args, namespace, external_secret)
        if (
            materialized.get("WOODPECKER_FORGEJO_CLIENT") == client_id
            and materialized.get("WOODPECKER_FORGEJO_SECRET") == client_secret
        ):
            break
        time.sleep(5)
    else:
        raise RuntimeError("ESO did not materialize the new Woodpecker credentials")

    kubectl(args, "-n", namespace, "rollout", "restart", "statefulset/woodpecker-server")
    kubectl(
        args,
        "-n",
        namespace,
        "rollout",
        "status",
        "statefulset/woodpecker-server",
        "--timeout=10m",
    )


def self_test() -> int:
    sample = """
    <meta name="_csrf" content="csrf-value">
    <div class="flex-item tw-items-center">
      <div class="flex-item-title">Woodpecker CI</div>
      <a href="/admin/applications/oauth2/42">Edit</a>
    </div>
    <input id="client-id" value="client-value" readonly>
    <input id="client-secret" value="secret-value" readonly>
    """
    failures: list[str] = []
    if csrf_token(sample) != "csrf-value":
        failures.append("CSRF token parser")
    if csrf_token("<form></form>", required=False) is not None:
        failures.append("optional CSRF token parser")
    if add_optional_csrf({"field": "value"}, "<form></form>") != {"field": "value"}:
        failures.append("optional CSRF field handling")
    if oauth_application_id(sample, APPLICATION_NAME) != "42":
        failures.append("system-wide application parser")
    if credential_from_page(sample, "client_id") != "client-value":
        failures.append("client ID parser")
    if credential_from_page(sample, "client_secret") != "secret-value":
        failures.append("client secret parser")
    if failures:
        print("[forgejo-woodpecker-oauth] self-test failed: " + ", ".join(failures))
        return 1
    print("[forgejo-woodpecker-oauth] self-test passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or rotate Forgejo's system-wide Woodpecker OAuth2 application.",
    )
    parser.add_argument("--kubeconfig", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="Regenerate the existing application's client secret.",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.kubeconfig is None or args.contract is None:
        parser.error("--kubeconfig and --contract are required")

    try:
        for command in ("bao", "kubectl"):
            require_command(command)
        if not os.environ.get("BAO_TOKEN"):
            raise RuntimeError("BAO_TOKEN is required")

        contract = load_contract(args.contract)
        forgejo = contract["platform"]["forgejo"]
        woodpecker = contract["platform"]["woodpecker"]
        namespace = forgejo["namespace"]
        admin_secret = get_kubernetes_secret(
            args,
            namespace,
            forgejo["admin_secret_name"],
        )
        ca_config = kubectl(
            args,
            "-n",
            namespace,
            "get",
            "configmap",
            "homelab-root-ca",
            "-o",
            "json",
        )
        ca_pem = json.loads(ca_config.stdout)["data"]["ca-bundle.crt"]

        session = ForgejoSession(forgejo["sso"]["forgejo_root_url"], ca_pem)
        applications = authenticate(
            session,
            admin_secret["username"],
            admin_secret["password"],
        )
        callback_url = f"https://{woodpecker['host']}/authorize"
        client_id, client_secret, changed = create_or_rotate_application(
            session,
            applications,
            callback_url,
            args.rotate,
        )

        mount = os.environ.get("BAO_KV_MOUNT", "secret").strip("/")
        bao_path = f"{mount}/{OPENBAO_PATH}"
        current, current_version = read_openbao(bao_path)
        if not changed:
            if current.get("forgejo_client") == client_id and str(
                current.get("bootstrap_provisional", "false")
            ).casefold() not in {"1", "true", "yes"}:
                reconcile_woodpecker(
                    args,
                    woodpecker["namespace"],
                    woodpecker["runtime_secret_name"],
                    client_id,
                    str(current["forgejo_secret"]),
                )
                print("[forgejo-woodpecker-oauth] application and OpenBao are already synchronized")
                return 0
            raise RuntimeError(
                "the system-wide application already exists but OpenBao does not "
                "contain its final credentials; rerun with --rotate to recover"
            )

        if not current.get("agent_secret"):
            raise RuntimeError(f"refusing to replace {bao_path}: agent_secret is missing")
        current["forgejo_client"] = client_id
        current["forgejo_secret"] = client_secret
        current["bootstrap_provisional"] = False
        write_openbao(bao_path, current, current_version)
        reconcile_woodpecker(
            args,
            woodpecker["namespace"],
            woodpecker["runtime_secret_name"],
            client_id,
            client_secret,
        )
        print(
            "[forgejo-woodpecker-oauth] system-wide application created/rotated; "
            "credentials stored in OpenBao and ESO refresh requested"
        )
        return 0
    except (
        KeyError,
        RuntimeError,
        TypeError,
        subprocess.CalledProcessError,
        urllib.error.URLError,
    ) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        else:
            message = str(exc)
        print(f"[forgejo-woodpecker-oauth] {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
