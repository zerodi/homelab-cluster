"""Render runtime workloads and enforce the repository image/security baseline."""

from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from ruamel.yaml import YAML

from homelabctl.project import ROOT
from homelabctl.runtime import CommandError, require, run
from homelabctl.yamlutil import load


@dataclass(frozen=True)
class HelmRender:
    release: str
    chart: str
    version_key: str
    namespace: str
    values: str
    repository: str | None = None
    enforce_baseline: bool = True


HELM_RENDERS = (
    HelmRender(
        "authentik",
        "authentik",
        "authentik",
        "authentik",
        "argocd/platform/identity/authentik/values.yaml",
        "https://charts.goauthentik.io",
    ),
    HelmRender(
        "authentik-postgresql",
        "oci://registry-1.docker.io/bitnamicharts/postgresql",
        "postgresql",
        "authentik",
        "argocd/platform/identity/authentik/postgresql/values.yaml",
    ),
    HelmRender(
        "authentik-redis",
        "oci://registry-1.docker.io/bitnamicharts/redis",
        "redis",
        "authentik",
        "argocd/platform/identity/authentik/redis/values.yaml",
    ),
    HelmRender(
        "forgejo",
        "oci://code.forgejo.org/forgejo-helm/forgejo",
        "forgejo",
        "forgejo",
        "argocd/platform/delivery/forgejo/values.yaml",
    ),
    HelmRender(
        "forgejo-postgresql",
        "oci://registry-1.docker.io/bitnamicharts/postgresql",
        "postgresql",
        "forgejo",
        "argocd/platform/delivery/forgejo/postgresql/values.yaml",
    ),
    HelmRender(
        "forgejo-valkey",
        "oci://registry-1.docker.io/bitnamicharts/valkey",
        "valkey",
        "forgejo",
        "argocd/platform/delivery/forgejo/valkey/values.yaml",
    ),
    HelmRender(
        "harbor",
        "harbor",
        "harbor",
        "harbor",
        "argocd/platform/delivery/harbor/values.yaml",
        "https://helm.goharbor.io",
    ),
    HelmRender(
        "harbor-postgresql",
        "oci://registry-1.docker.io/bitnamicharts/postgresql",
        "postgresql",
        "harbor",
        "argocd/platform/delivery/harbor/postgresql/values.yaml",
    ),
    HelmRender(
        "harbor-valkey",
        "oci://registry-1.docker.io/bitnamicharts/valkey",
        "valkey",
        "harbor",
        "argocd/platform/delivery/harbor/valkey/values.yaml",
    ),
    HelmRender(
        "woodpecker",
        "oci://ghcr.io/woodpecker-ci/helm/woodpecker",
        "woodpecker",
        "woodpecker",
        "argocd/platform/delivery/woodpecker/values.yaml",
    ),
    HelmRender(
        "kyverno",
        "kyverno",
        "kyverno",
        "kyverno",
        "argocd/platform/policy/kyverno/values.yaml",
        "https://kyverno.github.io/kyverno/",
        False,
    ),
    HelmRender(
        "reloader",
        "reloader",
        "reloader",
        "reloader",
        "/dev/null",
        "https://stakater.github.io/stakater-charts",
        False,
    ),
    HelmRender(
        "victoria-metrics",
        "victoria-metrics-single",
        "victoria_metrics_single",
        "observability",
        "argocd/platform/observability/victoria-metrics/values.yaml",
        "https://victoriametrics.github.io/helm-charts",
    ),
    HelmRender(
        "loki",
        "loki",
        "loki",
        "observability",
        "argocd/platform/observability/loki/values.yaml",
        "https://grafana-community.github.io/helm-charts",
    ),
    HelmRender(
        "tempo",
        "tempo",
        "tempo",
        "observability",
        "argocd/platform/observability/tempo/values.yaml",
        "https://grafana-community.github.io/helm-charts",
    ),
    HelmRender(
        "otel-collector",
        "opentelemetry-collector",
        "opentelemetry_collector",
        "observability",
        "argocd/platform/observability/otel-collector/values.yaml",
        "https://open-telemetry.github.io/opentelemetry-helm-charts",
    ),
    HelmRender(
        "otel-agent",
        "opentelemetry-collector",
        "opentelemetry_collector",
        "observability",
        "argocd/platform/observability/otel-agent/values.yaml",
        "https://open-telemetry.github.io/opentelemetry-helm-charts",
    ),
    HelmRender(
        "grafana",
        "grafana",
        "grafana",
        "observability",
        "argocd/platform/observability/grafana/values.yaml",
        "https://grafana-community.github.io/helm-charts",
    ),
    HelmRender(
        "velero",
        "velero",
        "velero",
        "velero",
        "argocd/platform/storage/velero/values.yaml",
        "https://vmware-tanzu.github.io/helm-charts",
    ),
)

KUSTOMIZE_RENDERS = (
    "argocd/apps/echo/resources",
    "argocd/platform/messaging/stalwart/resources",
    "argocd/platform/storage/garage/resources",
)

RAW_RENDERS = ("argocd/platform/delivery/forgejo/sso/job.yml",)

WORKLOAD_KINDS = {"Pod", "Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}
LATEST = re.compile(r":latest(?:@sha256:[0-9a-f]{64})?$")
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def _documents(value: str) -> list[dict[str, Any]]:
    return [item for item in YAML(typ="safe").load_all(value) if isinstance(item, dict)]


def _pod_spec(document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    kind = document.get("kind")
    if kind not in WORKLOAD_KINDS:
        return None
    annotations = document.get("metadata", {}).get("annotations") or {}
    if "test" in str(annotations.get("helm.sh/hook", "")).split(","):
        return None
    if kind == "Pod":
        return document.get("metadata", {}), document.get("spec", {})
    template = document.get("spec", {}).get("jobTemplate", {}).get("spec", {}).get("template")
    if kind != "CronJob":
        template = document.get("spec", {}).get("template")
    if not isinstance(template, dict):
        return None
    return template.get("metadata", {}), template.get("spec", {})


def _containers(spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        *list(spec.get("containers") or []),
        *list(spec.get("initContainers") or []),
        *list(spec.get("ephemeralContainers") or []),
    ]


def _has_resources(container: dict[str, Any]) -> bool:
    resources = container.get("resources") or {}
    requests = resources.get("requests") or {}
    limits = resources.get("limits") or {}
    return all(requests.get(name) and limits.get(name) for name in ("cpu", "memory"))


def _has_restricted_context(container: dict[str, Any]) -> bool:
    context = container.get("securityContext") or {}
    return (
        context.get("runAsNonRoot") is True
        and context.get("allowPrivilegeEscalation") is False
        and "ALL" in ((context.get("capabilities") or {}).get("drop") or [])
    )


def validate_documents(
    documents: list[dict[str, Any]], source: str, *, enforce_baseline: bool = True
) -> list[str]:
    errors: list[str] = []
    for document in documents:
        pod = _pod_spec(document)
        if pod is None:
            continue
        template_metadata, spec = pod
        metadata = document.get("metadata") or {}
        namespace = str(metadata.get("namespace") or "default")
        name = str(metadata.get("name") or "unnamed")
        labels = template_metadata.get("labels") or metadata.get("labels") or {}
        node_agent = namespace == "velero" and labels.get("name") == "node-agent"
        harbor = namespace == "harbor"

        pod_context = spec.get("securityContext") or {}
        seccomp = (pod_context.get("seccompProfile") or {}).get("type")
        if (
            enforce_baseline
            and not node_agent
            and not harbor
            and seccomp not in {"RuntimeDefault", "Localhost"}
        ):
            errors.append(f"{source}: {namespace}/{name}: pod seccompProfile is missing")

        for container in _containers(spec):
            container_name = str(container.get("name") or "unnamed")
            image = str(container.get("image") or "")
            image_tail = image.rsplit("/", 1)[-1]
            if not image or (":" not in image_tail and not DIGEST.search(image)):
                errors.append(
                    f"{source}: {namespace}/{name}/{container_name}: image has no tag or digest"
                )
            if LATEST.search(image):
                errors.append(
                    f"{source}: {namespace}/{name}/{container_name}: image uses latest: {image}"
                )
            if ("/bitnami/" in image or image.startswith("bitnami/")) and not DIGEST.search(image):
                errors.append(
                    f"{source}: {namespace}/{name}/{container_name}: Bitnami image is not digest-pinned"
                )
            if enforce_baseline and not _has_resources(container):
                errors.append(
                    f"{source}: {namespace}/{name}/{container_name}: cpu/memory requests or limits missing"
                )
            if enforce_baseline and not node_agent and not _has_restricted_context(container):
                errors.append(
                    f"{source}: {namespace}/{name}/{container_name}: restricted securityContext missing"
                )
    return errors


def _helm_render(spec: HelmRender, versions: dict[str, Any]) -> list[dict[str, Any]]:
    argv = [
        "helm",
        "template",
        spec.release,
        spec.chart,
        "--version",
        str(versions[spec.version_key]),
        "--namespace",
        spec.namespace,
        "--values",
        ROOT / spec.values,
    ]
    if spec.repository:
        argv.extend(["--repo", spec.repository])
    return _documents(run(argv, cwd=ROOT).stdout)


def _chart_applications() -> set[str]:
    applications: set[str] = set()
    for path in (ROOT / "argocd/platform").rglob("*.yaml"):
        if "applications" not in path.parts:
            continue
        document = load(path)
        if not isinstance(document, dict) or document.get("kind") != "Application":
            continue
        sources = document.get("spec", {}).get("sources") or []
        source = document.get("spec", {}).get("source") or {}
        if source:
            sources = [source, *sources]
        if any(item.get("chart") for item in sources):
            applications.add(str(document["metadata"]["name"]))
    return applications


def validate() -> int:
    require("helm", "kustomize")
    versions = load(ROOT / "versions.yaml")["charts"]
    errors: list[str] = []
    expected_releases = _chart_applications()
    configured_releases = {spec.release for spec in HELM_RENDERS}
    for release in sorted(expected_releases - configured_releases):
        errors.append(f"helm:{release}: chart Application is absent from the render gate")
    for release in sorted(configured_releases - expected_releases):
        errors.append(f"helm:{release}: render gate has no matching chart Application")

    def render(spec: HelmRender) -> tuple[HelmRender, list[dict[str, Any]] | CommandError]:
        try:
            return spec, _helm_render(spec, versions)
        except CommandError as exc:
            return spec, exc

    with ThreadPoolExecutor(max_workers=6) as executor:
        rendered = list(executor.map(render, HELM_RENDERS))
    for spec, result in rendered:
        if isinstance(result, CommandError):
            errors.append(f"helm:{spec.release}: {result}")
        else:
            errors.extend(
                validate_documents(
                    result, f"helm:{spec.release}", enforce_baseline=spec.enforce_baseline
                )
            )
    for path in KUSTOMIZE_RENDERS:
        documents = _documents(run(["kustomize", "build", ROOT / path], cwd=ROOT).stdout)
        errors.extend(validate_documents(documents, f"kustomize:{path}"))
    for path in RAW_RENDERS:
        errors.extend(validate_documents([load(ROOT / path)], f"yaml:{path}"))

    if errors:
        print("[runtime-workloads] validation failed", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("[runtime-workloads] passed: rendered images, resources, and security contexts comply")
    return 0


def main() -> int:
    return validate()


if __name__ == "__main__":
    raise SystemExit(main())
