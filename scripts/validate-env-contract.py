#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


PLACEHOLDER_REPO_URL = "https://git.example.invalid/replace-me/gitops.git"
DEFAULT_BASE_DOMAIN = "home.arpa"


def run(*args: str) -> str:
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return result.stdout


def run_allow_failure(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, capture_output=True, text=True)


def load_yaml(path: Path) -> Any:
    output = run("yq", "eval", "-o=json", ".", str(path))
    if not output.strip():
        return None
    return json.loads(output)


def get_path(data: Any, *parts: Any) -> Any:
    current = data
    for part in parts:
        current = current[part]
    return current


def set_path(data: Any, parts: tuple[Any, ...], value: Any) -> None:
    current = data
    for part in parts[:-1]:
        current = current[part]
    current[parts[-1]] = value


def yq_path(parts: tuple[Any, ...]) -> str:
    expression = "."
    for part in parts:
        if isinstance(part, int):
            expression += f"[{part}]"
        else:
            expression += f"[{json.dumps(part)}]"
    return expression


class Validator:
    def __init__(
        self,
        root: Path,
        mode: str,
        contract_path: Path,
        write: bool = False,
    ) -> None:
        self.root = root
        self.mode = mode
        self.contract_path = contract_path
        self.write = write
        self.errors: list[str] = []
        self.yaml_cache: dict[Path, Any] = {}
        self.text_cache: dict[Path, str] = {}
        self.yaml_updates: dict[Path, dict[tuple[Any, ...], Any]] = {}
        self.changed_text_files: set[Path] = set()

    def yaml(self, relpath: str) -> Any:
        path = self.root / relpath
        if path not in self.yaml_cache:
            self.yaml_cache[path] = load_yaml(path)
        return self.yaml_cache[path]

    def text(self, relpath: str) -> str:
        path = self.root / relpath
        if path not in self.text_cache:
            self.text_cache[path] = path.read_text(encoding="utf-8")
        return self.text_cache[path]

    def error(self, message: str) -> None:
        self.errors.append(message)

    def expect_equal(self, label: str, expected: Any, relpath: str, *parts: Any) -> None:
        try:
            actual = get_path(self.yaml(relpath), *parts)
        except Exception as exc:  # pragma: no cover
            self.error(f"{label}: missing path {parts!r} in {relpath}: {exc}")
            return
        if actual != expected:
            if self.write:
                path = self.root / relpath
                update_parts = tuple(parts)
                self.yaml_updates.setdefault(path, {})[update_parts] = expected
                set_path(self.yaml_cache[path], update_parts, expected)
                return
            self.error(
                f"{label}: {relpath} has {actual!r}, expected {expected!r}"
            )

    def expect_contains(self, label: str, relpath: str, expected: str) -> None:
        actual = self.text(relpath)
        if expected not in actual:
            self.error(f"{label}: {relpath} is missing {expected!r}")

    def expect_regex(self, label: str, relpath: str, pattern: str) -> None:
        actual = self.text(relpath)
        if re.search(pattern, actual, flags=re.MULTILINE) is None:
            self.error(f"{label}: {relpath} does not match /{pattern}/")

    def queue_yaml_update(
        self,
        path: Path,
        parts: tuple[Any, ...],
        expected: Any,
    ) -> None:
        data = self.yaml(str(path))
        try:
            actual = get_path(data, *parts)
        except Exception as exc:
            self.error(
                f"{path.relative_to(self.root)}: missing path {parts!r}: {exc}"
            )
            return
        if actual == expected:
            return
        self.yaml_updates.setdefault(path, {})[parts] = expected
        set_path(data, parts, expected)

    def sync_text_mirrors(self, env: dict[str, Any]) -> None:
        base = load_yaml(self.root / "envs/homelab.yaml")
        replacements: dict[str, str] = {}

        def add_replacement(old: Any, new: Any) -> None:
            if isinstance(old, (str, int)) and isinstance(new, (str, int)):
                old_text = str(old)
                new_text = str(new)
                if old_text and old_text != new_text:
                    replacements[old_text] = new_text

        def add_yaml_replacement(
            relpath: str,
            parts: tuple[Any, ...],
            new: Any,
        ) -> None:
            try:
                old = get_path(self.yaml(relpath), *parts)
            except Exception as exc:
                self.error(
                    f"{relpath}: cannot read current mirror {parts!r}: {exc}"
                )
                return
            add_replacement(old, new)

        add_replacement(base["gitops"]["repo_url"], env["gitops"]["repo_url"])
        add_yaml_replacement(
            "argocd/bootstrap/root-application.yaml",
            ("spec", "source", "repoURL"),
            env["gitops"]["repo_url"],
        )

        hostname_mirrors = {
            "authentik": (
                "argocd/platform/authentik/prereqs/certificate.yaml",
                ("spec", "dnsNames", 0),
            ),
            "forgejo": (
                "argocd/platform/forgejo/prereqs/certificate.yaml",
                ("spec", "dnsNames", 0),
            ),
            "garage": (
                "argocd/platform/garage/prereqs/certificate.yaml",
                ("spec", "dnsNames", 0),
            ),
            "harbor": (
                "argocd/platform/harbor/prereqs/certificate.yaml",
                ("spec", "dnsNames", 0),
            ),
            "woodpecker": (
                "argocd/platform/woodpecker/prereqs/certificate.yaml",
                ("spec", "dnsNames", 0),
            ),
            "echo": (
                "argocd/apps/echo/resources/certificate.yaml",
                ("spec", "dnsNames", 0),
            ),
            "grafana": (
                "argocd/platform/observability/prereqs/certificate.yaml",
                ("spec", "dnsNames", 0),
            ),
            "hubble": (
                "argocd/platform/hubble/httproute.yaml",
                ("spec", "hostnames", 0),
            ),
            "stalwart": (
                "argocd/platform/gateway/stalwart-admin-certificate.yaml",
                ("spec", "dnsNames", 0),
            ),
            "mail": (
                "argocd/platform/stalwart/prereqs/mail-certificate.yaml",
                ("spec", "dnsNames", 0),
            ),
        }
        for key, old_value in base["hosts"].items():
            add_replacement(old_value, env["hosts"][key])
            if key in hostname_mirrors:
                relpath, parts = hostname_mirrors[key]
                add_yaml_replacement(relpath, parts, env["hosts"][key])

        address_mirrors = {
            "authentik": "argocd/platform/authentik/prereqs/gateway.yaml",
            "echo": "argocd/apps/echo/resources/gateway.yaml",
            "grafana": "argocd/platform/observability/prereqs/gateway.yaml",
            "forgejo": "argocd/platform/forgejo/prereqs/gateway.yaml",
            "external": "argocd/platform/gateway/external-gateway.yaml",
            "internal": "argocd/platform/gateway/internal-gateway.yaml",
            "garage": "argocd/platform/garage/prereqs/gateway.yaml",
            "harbor": "argocd/platform/harbor/prereqs/gateway.yaml",
            "woodpecker": "argocd/platform/woodpecker/prereqs/gateway.yaml",
        }
        for key, old_value in base["platform"]["gateway"]["addresses"].items():
            add_replacement(
                old_value,
                env["platform"]["gateway"]["addresses"][key],
            )
            if key in address_mirrors:
                add_yaml_replacement(
                    address_mirrors[key],
                    (
                        "spec",
                        "infrastructure",
                        "annotations",
                        "io.cilium/lb-ipam-ips",
                    ),
                    env["platform"]["gateway"]["addresses"][key],
                )
        add_replacement(
            base["platform"]["stalwart"]["mail_load_balancer_ip"],
            env["platform"]["stalwart"]["mail_load_balancer_ip"],
        )
        add_yaml_replacement(
            "argocd/platform/stalwart/resources/mail-service.yaml",
            ("metadata", "annotations", "lbipam.cilium.io/ips"),
            env["platform"]["stalwart"]["mail_load_balancer_ip"],
        )
        add_replacement(
            base["storage"]["piraeus"]["storage_class"],
            env["storage"]["piraeus"]["storage_class"],
        )
        add_yaml_replacement(
            "argocd/platform/authentik/postgresql/values.yaml",
            ("primary", "persistence", "storageClass"),
            env["storage"]["piraeus"]["storage_class"],
        )
        add_replacement(
            base["platform"]["forgejo"]["admin_email"],
            env["platform"]["forgejo"]["admin_email"],
        )
        add_yaml_replacement(
            "argocd/platform/forgejo/values.yaml",
            ("gitea", "admin", "email"),
            env["platform"]["forgejo"]["admin_email"],
        )

        if self.errors or not replacements:
            return

        for path in sorted((self.root / "argocd").rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {
                ".md",
                ".yaml",
                ".yml",
            }:
                continue
            original = path.read_text(encoding="utf-8")
            updated = original
            for old, new in sorted(
                replacements.items(),
                key=lambda item: len(item[0]),
                reverse=True,
            ):
                updated = updated.replace(old, new)
            if updated != original:
                path.write_text(updated, encoding="utf-8")
                self.changed_text_files.add(path)
                self.text_cache.pop(path, None)
                self.yaml_cache.pop(path, None)

    def flush_yaml_updates(self) -> None:
        for path, updates in sorted(
            self.yaml_updates.items(),
            key=lambda item: str(item[0]),
        ):
            for parts, value in updates.items():
                environment = os.environ.copy()
                environment["ENV_CONTRACT_SYNC_VALUE"] = json.dumps(value)
                subprocess.run(
                    [
                        "yq",
                        "eval",
                        "-i",
                        (
                            f"{yq_path(parts)} = "
                            '(strenv(ENV_CONTRACT_SYNC_VALUE) | from_json)'
                        ),
                        str(path),
                    ],
                    check=True,
                    env=environment,
                )

    def report_errors(self) -> int:
        print("[env-contract] validation failed", file=sys.stderr)
        for issue in self.errors:
            print(f"  - {issue}", file=sys.stderr)
        print(file=sys.stderr)
        print(
            "Next actions: update envs/homelab.yaml or envs/homelab.override.yaml, then run task sync-env-contract.",
            file=sys.stderr,
        )
        return 1

    def validate(self) -> int:
        env = self.yaml(str(self.contract_path))
        hosts = env["hosts"]
        base_domain = env["cluster"]["base_domain"]
        gitops_repo = env["gitops"]["repo_url"]
        gitops_revision = env["gitops"]["revision"]

        auth_url = f"https://{hosts['authentik']}"
        forgejo_url = f"https://{hosts['forgejo']}"
        grafana_url = f"https://{hosts['grafana']}/"
        harbor_url = f"https://{hosts['harbor']}"
        woodpecker_url = f"https://{hosts['woodpecker']}"

        if self.mode == "strict":
            if gitops_repo == PLACEHOLDER_REPO_URL:
                self.error(
                    "gitops.repo_url still points to the intentionally invalid scaffold repoURL placeholder"
                )
            if base_domain == DEFAULT_BASE_DOMAIN:
                self.error(
                    "cluster.base_domain is still the scaffold default home.arpa; replace it before real GitOps bootstrap"
                )
            if env["platform"]["forgejo"]["admin_email"].endswith("@home.arpa"):
                self.error(
                    "platform.forgejo.admin_email still uses the scaffold default @home.arpa address"
                )

        for host_key, hostname in hosts.items():
            if not hostname.endswith(f".{base_domain}"):
                self.error(
                    f"hosts.{host_key}={hostname!r} does not match cluster.base_domain={base_domain!r}"
                )

        if env["platform"]["forgejo"]["root_url"] != f"{forgejo_url}/":
            self.error(
                "platform.forgejo.root_url must match hosts.forgejo with a trailing slash"
            )
        if env["platform"]["forgejo"]["sso"]["authentik_host"] != auth_url:
            self.error("platform.forgejo.sso.authentik_host must match hosts.authentik")
        if env["platform"]["forgejo"]["sso"]["forgejo_root_url"] != forgejo_url:
            self.error("platform.forgejo.sso.forgejo_root_url must match hosts.forgejo")
        expected_discovery_url = (
            f"{auth_url}/application/o/forgejo/.well-known/openid-configuration"
        )
        if env["platform"]["forgejo"]["sso"]["discovery_url"] != expected_discovery_url:
            self.error(
                "platform.forgejo.sso.discovery_url must match hosts.authentik and application_slug"
            )
        if env["platform"]["harbor"]["host"] != hosts["harbor"]:
            self.error("platform.harbor.host must match hosts.harbor")
        if env["platform"]["harbor"]["external_url"] != harbor_url:
            self.error("platform.harbor.external_url must match hosts.harbor")
        if env["platform"]["stalwart"]["admin_host"] != hosts["stalwart"]:
            self.error("platform.stalwart.admin_host must match hosts.stalwart")
        if env["platform"]["stalwart"]["mail_host"] != hosts["mail"]:
            self.error("platform.stalwart.mail_host must match hosts.mail")
        if env["platform"]["stalwart"]["public_url"] != f"https://{hosts['stalwart']}":
            self.error("platform.stalwart.public_url must match hosts.stalwart")
        if env["platform"]["woodpecker"]["host"] != hosts["woodpecker"]:
            self.error("platform.woodpecker.host must match hosts.woodpecker")
        if env["platform"]["woodpecker"]["forgejo_url"] != forgejo_url:
            self.error("platform.woodpecker.forgejo_url must match hosts.forgejo")
        if env["platform"]["observability"]["grafana"]["root_url"] != grafana_url:
            self.error(
                "platform.observability.grafana.root_url must match hosts.grafana with a trailing slash"
            )
        if env["apps"]["echo"]["host"] != hosts["echo"]:
            self.error("apps.echo.host must match hosts.echo")

        if self.write:
            if self.errors:
                return self.report_errors()
            self.sync_text_mirrors(env)

        for path in sorted(self.root.glob("argocd/**/*.[Yy][Aa][Mm][Ll]")):
            relpath = path.relative_to(self.root)
            data = load_yaml(path)
            if not isinstance(data, dict):
                continue

            if data.get("kind") == "Application":
                spec = data.get("spec", {})
                source = spec.get("source")
                if isinstance(source, dict) and source.get("path"):
                    if source.get("repoURL") != gitops_repo:
                        if self.write:
                            self.queue_yaml_update(
                                path,
                                ("spec", "source", "repoURL"),
                                gitops_repo,
                            )
                        else:
                            self.error(
                                f"gitops.repo_url: {relpath} has {source.get('repoURL')!r}, expected {gitops_repo!r}"
                            )
                    if source.get("targetRevision") != gitops_revision:
                        if self.write:
                            self.queue_yaml_update(
                                path,
                                ("spec", "source", "targetRevision"),
                                gitops_revision,
                            )
                        else:
                            self.error(
                                f"gitops.revision: {relpath} has {source.get('targetRevision')!r}, expected {gitops_revision!r}"
                            )

                for index, item in enumerate(spec.get("sources", [])):
                    if not isinstance(item, dict):
                        continue
                    if item.get("ref") == "values" or item.get("path"):
                        if item.get("repoURL") != gitops_repo:
                            if self.write:
                                self.queue_yaml_update(
                                    path,
                                    ("spec", "sources", index, "repoURL"),
                                    gitops_repo,
                                )
                            else:
                                self.error(
                                    f"gitops.repo_url: {relpath} has {item.get('repoURL')!r}, expected {gitops_repo!r}"
                                )
                        if item.get("targetRevision") != gitops_revision:
                            if self.write:
                                self.queue_yaml_update(
                                    path,
                                    ("spec", "sources", index, "targetRevision"),
                                    gitops_revision,
                                )
                            else:
                                self.error(
                                    f"gitops.revision: {relpath} has {item.get('targetRevision')!r}, expected {gitops_revision!r}"
                                )

            if data.get("kind") == "AppProject":
                source_repos = data.get("spec", {}).get("sourceRepos", [])
                if gitops_repo not in source_repos:
                    if self.write and source_repos:
                        self.queue_yaml_update(
                            path,
                            ("spec", "sourceRepos", 0),
                            gitops_repo,
                        )
                    else:
                        self.error(
                            f"gitops.repo_url: {relpath} sourceRepos does not include {gitops_repo!r}"
                        )

        if not self.write and gitops_repo != PLACEHOLDER_REPO_URL:
            leftover_repo = run_allow_failure(
                "rg",
                "-n",
                re.escape(PLACEHOLDER_REPO_URL),
                str(self.root / "argocd"),
            )
            if leftover_repo.returncode == 0 and leftover_repo.stdout.strip():
                self.error(
                    "leftover scaffold repoURL placeholder still exists under argocd/:\n"
                    + "\n".join(
                        line.replace(f"{self.root}/", "")
                        for line in leftover_repo.stdout.splitlines()
                    )
                )

        if not self.write and base_domain != DEFAULT_BASE_DOMAIN:
            base_contract = load_yaml(self.root / "envs/homelab.yaml")
            scaffold_literals = [
                *base_contract["hosts"].values(),
                base_contract["platform"]["forgejo"]["admin_email"],
            ]
            home_arpa_hits = run_allow_failure(
                "rg",
                "-n",
                "|".join(re.escape(value) for value in scaffold_literals),
                str(self.root / "argocd"),
            )
            if home_arpa_hits.returncode == 0 and home_arpa_hits.stdout.strip():
                self.error(
                    "leftover scaffold hostname/email literals still exist under argocd/:\n"
                    + "\n".join(
                        line.replace(f"{self.root}/", "")
                        for line in home_arpa_hits.stdout.splitlines()
                    )
                )

        self.expect_equal(
            "gateway class",
            env["platform"]["gateway"]["gateway_class_name"],
            "argocd/platform/gateway/external-gateway.yaml",
            "spec",
            "gatewayClassName",
        )
        self.expect_equal(
            "external gateway address",
            env["platform"]["gateway"]["addresses"]["external"],
            "argocd/platform/gateway/external-gateway.yaml",
            "spec",
            "infrastructure",
            "annotations",
            "io.cilium/lb-ipam-ips",
        )
        self.expect_equal(
            "gateway class",
            env["platform"]["gateway"]["gateway_class_name"],
            "argocd/platform/gateway/internal-gateway.yaml",
            "spec",
            "gatewayClassName",
        )
        self.expect_equal(
            "internal gateway address",
            env["platform"]["gateway"]["addresses"]["internal"],
            "argocd/platform/gateway/internal-gateway.yaml",
            "spec",
            "infrastructure",
            "annotations",
            "io.cilium/lb-ipam-ips",
        )

        coredns_path = "argocd/platform/gateway/coredns-home-arpa-overrides.yaml"
        for app_name, address_key in {
            "authentik": "authentik",
            "echo": "echo",
            "grafana": "grafana",
            "forgejo": "forgejo",
            "hubble": "internal",
            "garage": "garage",
            "stalwart": "external",
        }.items():
            self.expect_contains(
                f"coredns host override for {app_name}",
                coredns_path,
                f"{env['platform']['gateway']['addresses'][address_key]} {hosts[app_name]}",
            )
        self.expect_contains(
            "coredns host override for mail",
            coredns_path,
            f"{env['platform']['stalwart']['mail_load_balancer_ip']} {hosts['mail']}",
        )

        storage_class = env["storage"]["piraeus"]["storage_class"]
        for relpath, parts in [
            ("argocd/platform/authentik/postgresql/values.yaml", ("primary", "persistence", "storageClass")),
            ("argocd/platform/authentik/redis/values.yaml", ("master", "persistence", "storageClass")),
            ("argocd/platform/forgejo/postgresql/values.yaml", ("primary", "persistence", "storageClass")),
            ("argocd/platform/forgejo/valkey/values.yaml", ("primary", "persistence", "storageClass")),
            ("argocd/platform/harbor/postgresql/values.yaml", ("primary", "persistence", "storageClass")),
            ("argocd/platform/harbor/valkey/values.yaml", ("primary", "persistence", "storageClass")),
            ("argocd/platform/forgejo/values.yaml", ("persistence", "storageClass")),
            ("argocd/platform/observability/grafana/values.yaml", ("persistence", "storageClassName")),
        ]:
            self.expect_equal("storage class", storage_class, relpath, *parts)

        self.expect_equal(
            "woodpecker server storage class",
            env["platform"]["woodpecker"]["server_storage_class"],
            "argocd/platform/woodpecker/values.yaml",
            "server",
            "persistentVolume",
            "storageClass",
        )
        self.expect_equal(
            "woodpecker pipeline storage class",
            env["platform"]["woodpecker"]["server_storage_class"],
            "argocd/platform/woodpecker/values.yaml",
            "agent",
            "env",
            "WOODPECKER_BACKEND_K8S_STORAGE_CLASS",
        )
        self.expect_equal(
            "woodpecker server storage size",
            env["platform"]["woodpecker"]["server_storage_size"],
            "argocd/platform/woodpecker/values.yaml",
            "server",
            "persistentVolume",
            "size",
        )
        self.expect_equal(
            "woodpecker pipeline volume size",
            env["platform"]["woodpecker"]["pipeline_volume_size"],
            "argocd/platform/woodpecker/values.yaml",
            "agent",
            "env",
            "WOODPECKER_BACKEND_K8S_VOLUME_SIZE",
        )

        self.expect_equal(
            "garage image",
            f"{env['platform']['garage']['image']}:{env['platform']['garage']['image_tag']}",
            "argocd/platform/garage/resources/statefulset.yaml",
            "spec",
            "template",
            "spec",
            "containers",
            0,
            "image",
        )
        self.expect_equal(
            "stalwart image",
            f"{env['platform']['stalwart']['image']}:{env['platform']['stalwart']['image_tag']}",
            "argocd/platform/stalwart/resources/statefulset.yaml",
            "spec",
            "template",
            "spec",
            "containers",
            0,
            "image",
        )
        self.expect_equal(
            "stalwart storage class",
            env["platform"]["stalwart"]["storage_class"],
            "argocd/platform/stalwart/resources/statefulset.yaml",
            "spec",
            "volumeClaimTemplates",
            0,
            "spec",
            "storageClassName",
        )
        self.expect_equal(
            "stalwart storage size",
            env["platform"]["stalwart"]["storage_size"],
            "argocd/platform/stalwart/resources/statefulset.yaml",
            "spec",
            "volumeClaimTemplates",
            0,
            "spec",
            "resources",
            "requests",
            "storage",
        )
        self.expect_equal(
            "stalwart mail load balancer address",
            env["platform"]["stalwart"]["mail_load_balancer_ip"],
            "argocd/platform/stalwart/resources/mail-service.yaml",
            "metadata",
            "annotations",
            "lbipam.cilium.io/ips",
        )
        self.expect_equal(
            "stalwart mail hostname",
            env["platform"]["stalwart"]["mail_host"],
            "argocd/platform/stalwart/resources/statefulset.yaml",
            "spec",
            "template",
            "spec",
            "containers",
            0,
            "env",
            0,
            "value",
        )
        self.expect_equal(
            "stalwart public url",
            env["platform"]["stalwart"]["public_url"],
            "argocd/platform/stalwart/resources/statefulset.yaml",
            "spec",
            "template",
            "spec",
            "containers",
            0,
            "env",
            1,
            "value",
        )
        self.expect_equal(
            "garage secret name",
            env["platform"]["garage"]["runtime_secret_name"],
            "argocd/platform/garage/resources/statefulset.yaml",
            "spec",
            "template",
            "spec",
            "volumes",
            0,
            "secret",
            "secretName",
        )
        self.expect_equal(
            "garage storage class",
            env["platform"]["garage"]["storage_class"],
            "argocd/platform/garage/resources/statefulset.yaml",
            "spec",
            "volumeClaimTemplates",
            0,
            "spec",
            "storageClassName",
        )
        self.expect_equal(
            "garage storage size",
            env["platform"]["garage"]["size"],
            "argocd/platform/garage/resources/statefulset.yaml",
            "spec",
            "volumeClaimTemplates",
            0,
            "spec",
            "resources",
            "requests",
            "storage",
        )

        self.expect_equal(
            "authentik host",
            auth_url,
            "argocd/platform/authentik/values.yaml",
            "authentik",
            "host",
        )
        self.expect_equal(
            "authentik outpost host",
            auth_url,
            "argocd/platform/authentik/values.yaml",
            "authentik",
            "outposts",
            "authentik_host",
        )
        self.expect_equal(
            "authentik outpost browser host",
            auth_url,
            "argocd/platform/authentik/values.yaml",
            "authentik",
            "outposts",
            "authentik_host_browser",
        )
        self.expect_equal(
            "authentik runtime secret name",
            env["platform"]["authentik"]["runtime_secret_name"],
            "argocd/platform/authentik/values.yaml",
            "authentik",
            "existingSecret",
            "secretName",
        )
        self.expect_equal(
            "authentik postgresql host",
            env["platform"]["authentik"]["postgresql"]["host"],
            "argocd/platform/authentik/values.yaml",
            "authentik",
            "postgresql",
            "host",
        )
        self.expect_equal(
            "authentik postgresql database",
            env["platform"]["authentik"]["postgresql"]["database"],
            "argocd/platform/authentik/values.yaml",
            "authentik",
            "postgresql",
            "name",
        )
        self.expect_equal(
            "authentik postgresql user",
            env["platform"]["authentik"]["postgresql"]["user"],
            "argocd/platform/authentik/values.yaml",
            "authentik",
            "postgresql",
            "user",
        )
        self.expect_equal(
            "authentik redis host",
            env["platform"]["authentik"]["redis"]["host"],
            "argocd/platform/authentik/values.yaml",
            "authentik",
            "redis",
            "host",
        )

        self.expect_equal(
            "forgejo admin secret name",
            env["platform"]["forgejo"]["admin_secret_name"],
            "argocd/platform/forgejo/values.yaml",
            "gitea",
            "admin",
            "existingSecret",
        )
        self.expect_equal(
            "forgejo admin email",
            env["platform"]["forgejo"]["admin_email"],
            "argocd/platform/forgejo/values.yaml",
            "gitea",
            "admin",
            "email",
        )
        self.expect_equal(
            "forgejo root url",
            env["platform"]["forgejo"]["root_url"],
            "argocd/platform/forgejo/values.yaml",
            "gitea",
            "config",
            "server",
            "ROOT_URL",
        )
        self.expect_equal(
            "forgejo runtime config secret name",
            env["platform"]["forgejo"]["runtime_config_secret_name"],
            "argocd/platform/forgejo/values.yaml",
            "gitea",
            "additionalConfigSources",
            0,
            "secret",
            "secretName",
        )
        self.expect_equal(
            "forgejo postgresql username",
            env["platform"]["forgejo"]["postgresql"]["user"],
            "argocd/platform/forgejo/postgresql/values.yaml",
            "auth",
            "username",
        )
        self.expect_equal(
            "forgejo postgresql database",
            env["platform"]["forgejo"]["postgresql"]["database"],
            "argocd/platform/forgejo/postgresql/values.yaml",
            "auth",
            "database",
        )

        self.expect_equal(
            "harbor external url",
            env["platform"]["harbor"]["external_url"],
            "argocd/platform/harbor/values.yaml",
            "externalURL",
        )
        self.expect_equal(
            "harbor runtime secret name",
            env["platform"]["harbor"]["runtime_secret_name"],
            "argocd/platform/harbor/values.yaml",
            "existingSecretAdminPassword",
        )
        self.expect_equal(
            "harbor postgresql host",
            env["platform"]["harbor"]["postgresql"]["host"],
            "argocd/platform/harbor/values.yaml",
            "database",
            "external",
            "host",
        )
        self.expect_equal(
            "harbor postgresql database",
            env["platform"]["harbor"]["postgresql"]["database"],
            "argocd/platform/harbor/values.yaml",
            "database",
            "external",
            "coreDatabase",
        )
        self.expect_equal(
            "harbor postgresql user",
            env["platform"]["harbor"]["postgresql"]["user"],
            "argocd/platform/harbor/values.yaml",
            "database",
            "external",
            "username",
        )
        self.expect_equal(
            "harbor valkey address",
            env["platform"]["harbor"]["valkey"]["addr"],
            "argocd/platform/harbor/values.yaml",
            "redis",
            "external",
            "addr",
        )
        harbor_valkey_addr = env["platform"]["harbor"]["valkey"]["addr"]
        harbor_redis_urls = {
            "REDIS_URL_CORE": (
                f"redis://:{{{{ .password | urlquery }}}}@{harbor_valkey_addr}/0"
                "?idle_timeout_seconds=30"
            ),
            "REDIS_URL_REGISTRY": (
                f"redis://:{{{{ .password | urlquery }}}}@{harbor_valkey_addr}/2"
                "?idle_timeout_seconds=30"
            ),
            "REDIS_URL_HARBOR": (
                f"redis://:{{{{ .password | urlquery }}}}@{harbor_valkey_addr}/0"
                "?idle_timeout_seconds=30"
            ),
            "REDIS_URL_CACHE": (
                f"redis://:{{{{ .password | urlquery }}}}@{harbor_valkey_addr}/0"
                "?idle_timeout_seconds=30"
            ),
            "REDIS_URL_JOBSERVICE": (
                f"redis://:{{{{ .password | urlquery }}}}@{harbor_valkey_addr}/1"
            ),
            "REDIS_URL_TRIVY": (
                f"redis://:{{{{ .password | urlquery }}}}@{harbor_valkey_addr}/5"
                "?idle_timeout_seconds=30"
            ),
        }
        for key, expected in harbor_redis_urls.items():
            self.expect_equal(
                f"harbor derived valkey URL {key}",
                expected,
                "argocd/platform/harbor/prereqs/valkey-auth-external-secret.yaml",
                "spec",
                "target",
                "template",
                "data",
                key,
            )

        self.expect_equal(
            "woodpecker runtime secret name",
            env["platform"]["woodpecker"]["runtime_secret_name"],
            "argocd/platform/woodpecker/values.yaml",
            "server",
            "extraSecretNamesForEnvFrom",
            0,
        )
        self.expect_equal(
            "woodpecker runtime secret name",
            env["platform"]["woodpecker"]["runtime_secret_name"],
            "argocd/platform/woodpecker/values.yaml",
            "agent",
            "extraSecretNamesForEnvFrom",
            0,
        )
        self.expect_equal(
            "woodpecker host",
            woodpecker_url,
            "argocd/platform/woodpecker/values.yaml",
            "server",
            "env",
            "WOODPECKER_HOST",
        )
        self.expect_equal(
            "woodpecker forgejo url",
            env["platform"]["woodpecker"]["forgejo_url"],
            "argocd/platform/woodpecker/values.yaml",
            "server",
            "env",
            "WOODPECKER_FORGEJO_URL",
        )

        self.expect_equal(
            "grafana admin secret name",
            env["platform"]["observability"]["grafana"]["admin_secret_name"],
            "argocd/platform/observability/grafana/values.yaml",
            "admin",
            "existingSecret",
        )
        self.expect_equal(
            "grafana root url",
            env["platform"]["observability"]["grafana"]["root_url"],
            "argocd/platform/observability/grafana/values.yaml",
            "grafana.ini",
            "server",
            "root_url",
        )
        self.expect_equal(
            "grafana domain",
            hosts["grafana"],
            "argocd/platform/observability/grafana/values.yaml",
            "grafana.ini",
            "server",
            "domain",
        )

        self.expect_equal(
            "velero credentials secret name",
            env["platform"]["velero"]["credentials_secret_name"],
            "argocd/platform/velero/values.yaml",
            "credentials",
            "existingSecret",
        )
        self.expect_equal(
            "velero bucket",
            env["platform"]["velero"]["bucket"],
            "argocd/platform/velero/values.yaml",
            "configuration",
            "backupStorageLocation",
            0,
            "bucket",
        )
        self.expect_equal(
            "velero prefix",
            env["platform"]["velero"]["prefix"],
            "argocd/platform/velero/values.yaml",
            "configuration",
            "backupStorageLocation",
            0,
            "prefix",
        )
        self.expect_equal(
            "velero region",
            env["platform"]["velero"]["region"],
            "argocd/platform/velero/values.yaml",
            "configuration",
            "backupStorageLocation",
            0,
            "config",
            "region",
        )
        self.expect_equal(
            "velero s3 url",
            env["platform"]["velero"]["s3_url"],
            "argocd/platform/velero/values.yaml",
            "configuration",
            "backupStorageLocation",
            0,
            "config",
            "s3Url",
        )

        hostname_checks = [
            ("authentik certificate", hosts["authentik"], "argocd/platform/authentik/prereqs/certificate.yaml", ("spec", "dnsNames", 0)),
            ("authentik gateway", hosts["authentik"], "argocd/platform/authentik/prereqs/gateway.yaml", ("spec", "listeners", 0, "hostname")),
            ("authentik https gateway", hosts["authentik"], "argocd/platform/authentik/prereqs/gateway.yaml", ("spec", "listeners", 1, "hostname")),
            ("forgejo certificate", hosts["forgejo"], "argocd/platform/forgejo/prereqs/certificate.yaml", ("spec", "dnsNames", 0)),
            ("forgejo gateway", hosts["forgejo"], "argocd/platform/forgejo/prereqs/gateway.yaml", ("spec", "listeners", 0, "hostname")),
            ("forgejo https gateway", hosts["forgejo"], "argocd/platform/forgejo/prereqs/gateway.yaml", ("spec", "listeners", 1, "hostname")),
            ("harbor certificate", hosts["harbor"], "argocd/platform/harbor/prereqs/certificate.yaml", ("spec", "dnsNames", 0)),
            ("harbor gateway", hosts["harbor"], "argocd/platform/harbor/prereqs/gateway.yaml", ("spec", "listeners", 0, "hostname")),
            ("harbor https gateway", hosts["harbor"], "argocd/platform/harbor/prereqs/gateway.yaml", ("spec", "listeners", 1, "hostname")),
            ("woodpecker certificate", hosts["woodpecker"], "argocd/platform/woodpecker/prereqs/certificate.yaml", ("spec", "dnsNames", 0)),
            ("woodpecker gateway", hosts["woodpecker"], "argocd/platform/woodpecker/prereqs/gateway.yaml", ("spec", "listeners", 0, "hostname")),
            ("woodpecker https gateway", hosts["woodpecker"], "argocd/platform/woodpecker/prereqs/gateway.yaml", ("spec", "listeners", 1, "hostname")),
            ("garage certificate", hosts["garage"], "argocd/platform/garage/prereqs/certificate.yaml", ("spec", "dnsNames", 0)),
            ("garage gateway", hosts["garage"], "argocd/platform/garage/prereqs/gateway.yaml", ("spec", "listeners", 0, "hostname")),
            ("garage https gateway", hosts["garage"], "argocd/platform/garage/prereqs/gateway.yaml", ("spec", "listeners", 1, "hostname")),
            ("grafana certificate", hosts["grafana"], "argocd/platform/observability/prereqs/certificate.yaml", ("spec", "dnsNames", 0)),
            ("grafana gateway", hosts["grafana"], "argocd/platform/observability/prereqs/gateway.yaml", ("spec", "listeners", 0, "hostname")),
            ("grafana https gateway", hosts["grafana"], "argocd/platform/observability/prereqs/gateway.yaml", ("spec", "listeners", 1, "hostname")),
            ("echo certificate", hosts["echo"], "argocd/apps/echo/resources/certificate.yaml", ("spec", "dnsNames", 0)),
            ("echo gateway", hosts["echo"], "argocd/apps/echo/resources/gateway.yaml", ("spec", "listeners", 0, "hostname")),
            ("echo https gateway", hosts["echo"], "argocd/apps/echo/resources/gateway.yaml", ("spec", "listeners", 1, "hostname")),
            ("hubble route", hosts["hubble"], "argocd/platform/hubble/httproute.yaml", ("spec", "hostnames", 0)),
            ("stalwart admin certificate", hosts["stalwart"], "argocd/platform/gateway/stalwart-admin-certificate.yaml", ("spec", "dnsNames", 0)),
            ("stalwart gateway listener", hosts["stalwart"], "argocd/platform/gateway/external-gateway.yaml", ("spec", "listeners", 1, "hostname")),
            ("stalwart mail certificate", hosts["mail"], "argocd/platform/stalwart/prereqs/mail-certificate.yaml", ("spec", "dnsNames", 0)),
        ]
        for label, expected, relpath, parts in hostname_checks:
            self.expect_equal(label, expected, relpath, *parts)

        for relpath, hostname in [
            ("argocd/platform/authentik/prereqs/httproute.yaml", hosts["authentik"]),
            ("argocd/platform/authentik/prereqs/redirect-httproute.yaml", hosts["authentik"]),
            ("argocd/platform/forgejo/prereqs/httproute.yaml", hosts["forgejo"]),
            ("argocd/platform/forgejo/prereqs/redirect-httproute.yaml", hosts["forgejo"]),
            ("argocd/platform/harbor/prereqs/httproute.yaml", hosts["harbor"]),
            ("argocd/platform/harbor/prereqs/redirect-httproute.yaml", hosts["harbor"]),
            ("argocd/platform/woodpecker/prereqs/httproute.yaml", hosts["woodpecker"]),
            ("argocd/platform/woodpecker/prereqs/redirect-httproute.yaml", hosts["woodpecker"]),
            ("argocd/platform/garage/prereqs/httproute.yaml", hosts["garage"]),
            ("argocd/platform/garage/prereqs/redirect-httproute.yaml", hosts["garage"]),
            ("argocd/platform/observability/prereqs/httproute.yaml", hosts["grafana"]),
            ("argocd/platform/observability/prereqs/redirect-httproute.yaml", hosts["grafana"]),
            ("argocd/apps/echo/resources/httproute.yaml", hosts["echo"]),
            ("argocd/apps/echo/resources/redirect-httproute.yaml", hosts["echo"]),
            ("argocd/platform/stalwart/resources/httproute.yaml", hosts["stalwart"]),
            ("argocd/platform/stalwart/resources/redirect-httproute.yaml", hosts["stalwart"]),
        ]:
            self.expect_equal("route hostname", hostname, relpath, "spec", "hostnames", 0)

        self.expect_equal(
            "forgejo sso provider name",
            env["platform"]["forgejo"]["sso"]["provider_name"],
            "argocd/platform/authentik/prereqs/forgejo-sso-configmap.yaml",
            "data",
            "provider_name",
        )
        self.expect_equal(
            "forgejo sso application slug",
            env["platform"]["forgejo"]["sso"]["application_slug"],
            "argocd/platform/authentik/prereqs/forgejo-sso-configmap.yaml",
            "data",
            "application_slug",
        )
        self.expect_equal(
            "forgejo sso discovery url",
            env["platform"]["forgejo"]["sso"]["discovery_url"],
            "argocd/platform/authentik/prereqs/forgejo-sso-configmap.yaml",
            "data",
            "discovery_url",
        )
        self.expect_equal(
            "forgejo sso authentik host",
            env["platform"]["forgejo"]["sso"]["authentik_host"],
            "argocd/platform/authentik/prereqs/forgejo-sso-configmap.yaml",
            "data",
            "authentik_host",
        )
        self.expect_equal(
            "forgejo sso forgejo root url",
            env["platform"]["forgejo"]["sso"]["forgejo_root_url"],
            "argocd/platform/authentik/prereqs/forgejo-sso-configmap.yaml",
            "data",
            "forgejo_root_url",
        )
        self.expect_equal(
            "forgejo sso discovery url",
            env["platform"]["forgejo"]["sso"]["discovery_url"],
            "argocd/platform/forgejo/prereqs/forgejo-sso-configmap.yml",
            "data",
            "discovery_url",
        )
        self.expect_contains(
            "forgejo sso blueprint callback url",
            "argocd/platform/authentik/prereqs/forgejo-sso-blueprint-template-configmap.yml",
            f'https://{hosts["forgejo"]}/user/oauth2/authentik/callback',
        )
        self.expect_contains(
            "forgejo sso blueprint launch url",
            "argocd/platform/authentik/prereqs/forgejo-sso-blueprint-template-configmap.yml",
            env["platform"]["forgejo"]["root_url"],
        )

        external_secret_checks = [
            ("authentik runtime secret target", env["platform"]["authentik"]["runtime_secret_name"], "argocd/platform/authentik/prereqs/runtime-external-secret.yaml", ("metadata", "name")),
            ("authentik runtime secret target", env["platform"]["authentik"]["runtime_secret_name"], "argocd/platform/authentik/prereqs/runtime-external-secret.yaml", ("spec", "target", "name")),
            ("authentik postgresql secret name", env["platform"]["authentik"]["postgresql_auth_secret_name"], "argocd/platform/authentik/prereqs/postgresql-auth-external-secret.yaml", ("metadata", "name")),
            ("authentik redis secret name", env["platform"]["authentik"]["redis_auth_secret_name"], "argocd/platform/authentik/prereqs/redis-auth-external-secret.yaml", ("metadata", "name")),
            ("forgejo admin secret name", env["platform"]["forgejo"]["admin_secret_name"], "argocd/platform/forgejo/prereqs/admin-external-secret.yaml", ("metadata", "name")),
            ("forgejo oidc secret name", env["platform"]["forgejo"]["oidc_secret_name"], "argocd/platform/forgejo/prereqs/oidc-external-secret.yaml", ("metadata", "name")),
            ("forgejo runtime config secret name", env["platform"]["forgejo"]["runtime_config_secret_name"], "argocd/platform/forgejo/prereqs/runtime-config-external-secret.yaml", ("metadata", "name")),
            ("forgejo postgresql auth secret name", env["platform"]["forgejo"]["postgresql_auth_secret_name"], "argocd/platform/forgejo/prereqs/postgresql-auth-external-secret.yaml", ("metadata", "name")),
            ("forgejo valkey auth secret name", env["platform"]["forgejo"]["valkey_auth_secret_name"], "argocd/platform/forgejo/prereqs/valkey-auth-external-secret.yaml", ("metadata", "name")),
            ("harbor runtime secret name", env["platform"]["harbor"]["runtime_secret_name"], "argocd/platform/harbor/prereqs/runtime-external-secret.yaml", ("metadata", "name")),
            ("harbor postgresql auth secret name", env["platform"]["harbor"]["postgresql_auth_secret_name"], "argocd/platform/harbor/prereqs/postgresql-auth-external-secret.yaml", ("metadata", "name")),
            ("harbor valkey auth secret name", env["platform"]["harbor"]["valkey_auth_secret_name"], "argocd/platform/harbor/prereqs/valkey-auth-external-secret.yaml", ("metadata", "name")),
            ("stalwart runtime secret name", env["platform"]["stalwart"]["runtime_secret_name"], "argocd/platform/stalwart/prereqs/runtime-external-secret.yaml", ("metadata", "name")),
            ("stalwart runtime secret target", env["platform"]["stalwart"]["runtime_secret_name"], "argocd/platform/stalwart/prereqs/runtime-external-secret.yaml", ("spec", "target", "name")),
            ("woodpecker runtime secret name", env["platform"]["woodpecker"]["runtime_secret_name"], "argocd/platform/woodpecker/prereqs/runtime-external-secret.yaml", ("metadata", "name")),
            ("grafana admin secret name", env["platform"]["observability"]["grafana"]["admin_secret_name"], "argocd/platform/observability/prereqs/grafana-admin-external-secret.yaml", ("metadata", "name")),
            ("garage runtime secret name", env["platform"]["garage"]["runtime_secret_name"], "argocd/platform/garage/prereqs/runtime-external-secret.yaml", ("metadata", "name")),
            ("velero credentials secret name", env["platform"]["velero"]["credentials_secret_name"], "argocd/platform/velero/prereqs/credentials-external-secret.yaml", ("metadata", "name")),
        ]
        for label, expected, relpath, parts in external_secret_checks:
            self.expect_equal(label, expected, relpath, *parts)

        if self.errors:
            return self.report_errors()

        if self.write:
            self.flush_yaml_updates()
            changed_paths = self.changed_text_files | set(self.yaml_updates)
            for path in sorted(changed_paths):
                print(
                    f"[env-contract] synchronized {path.relative_to(self.root)}"
                )
            return Validator(
                root=self.root,
                mode=self.mode,
                contract_path=self.contract_path,
            ).validate()

        print(
            f"[env-contract] validation passed in {self.mode} mode for {self.contract_path} and argocd/",
        )
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the effective homelab environment contract against argocd/ consumers.",
    )
    parser.add_argument(
        "--mode",
        choices=("scaffold", "strict"),
        default="scaffold",
        help="scaffold checks mapping consistency; strict additionally fails on shipped placeholder defaults.",
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=None,
        help="Use an explicit effective contract instead of rendering the base and optional override.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Synchronize mapped argocd/ consumers before validating them.",
    )
    return parser.parse_args()


def resolve_explicit_contract(root: Path, raw_path: Path) -> Path:
    if raw_path.is_absolute():
        return raw_path

    root_candidate = root / raw_path
    if root_candidate.is_file():
        return root_candidate.resolve()

    infrastructure_candidate = root / "infrastructure" / raw_path
    return infrastructure_candidate.resolve()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    configured_path = args.contract
    if configured_path is None:
        env_path = os.environ.get("TF_VAR_environment_contract_path")
        if env_path:
            configured_path = Path(env_path)

    if configured_path is not None:
        contract_path = resolve_explicit_contract(root, configured_path)
    else:
        rendered_path = run(str(root / "scripts/render-environment-contract.sh"))
        contract_path = Path(rendered_path.strip()).resolve()

    if not contract_path.is_file():
        print(
            f"[env-contract] effective contract not found: {contract_path}",
            file=sys.stderr,
        )
        return 1

    return Validator(
        root=root,
        mode=args.mode,
        contract_path=contract_path,
        write=args.write,
    ).validate()


if __name__ == "__main__":
    raise SystemExit(main())
