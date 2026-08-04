#!/usr/bin/env python3

from __future__ import annotations

import copy
import ipaddress
import json
import re
import sys
from typing import Any


SERVICE_ADDRESS_OFFSETS = {
    "authentik": 231,
    "echo": 232,
    "grafana": 233,
    "forgejo": 234,
    "external": 235,
    "internal": 236,
    "garage": 237,
    "harbor": 238,
    "woodpecker": 239,
}
MAIL_ADDRESS_OFFSET = 240
REQUIRED_SUBDOMAINS = {
    "argocd",
    "authentik",
    "echo",
    "forgejo",
    "garage",
    "grafana",
    "harbor",
    "hubble",
    "mail",
    "minio",
    "stalwart",
    "woodpecker",
}


class ContractError(ValueError):
    pass


def validate_dns_name(value: str, field: str) -> None:
    if len(value) > 253:
        raise ContractError(f"{field} exceeds the 253-character DNS limit")
    for label in value.split("."):
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label):
            raise ContractError(f"{field} contains an invalid DNS label: {label!r}")


def materialize_contract(raw_contract: dict[str, Any]) -> dict[str, Any]:
    contract = copy.deepcopy(raw_contract)

    try:
        base_domain = contract["cluster"]["base_domain"].strip(".")
        ipv4_cidr = contract["cluster"]["ipv4_cidr"]
        subdomains = contract["service_subdomains"]
    except (KeyError, TypeError, AttributeError) as exc:
        raise ContractError(
            "contract requires cluster.base_domain, cluster.ipv4_cidr, and service_subdomains"
        ) from exc

    if not base_domain:
        raise ContractError("cluster.base_domain must not be empty")
    validate_dns_name(base_domain, "cluster.base_domain")

    try:
        network = ipaddress.ip_network(ipv4_cidr, strict=True)
    except ValueError as exc:
        raise ContractError(f"cluster.ipv4_cidr is invalid: {exc}") from exc

    if network.version != 4 or network.prefixlen != 24:
        raise ContractError("cluster.ipv4_cidr must be a canonical IPv4 /24 network")

    if not isinstance(subdomains, dict):
        raise ContractError("service_subdomains must be a mapping")

    missing_subdomains = sorted(REQUIRED_SUBDOMAINS - set(subdomains))
    if missing_subdomains:
        raise ContractError(
            "service_subdomains is missing: " + ", ".join(missing_subdomains)
        )

    hosts: dict[str, str] = {}
    for service, subdomain in subdomains.items():
        if not isinstance(subdomain, str) or not subdomain.strip("."):
            raise ContractError(f"service_subdomains.{service} must not be empty")
        normalized = subdomain.strip(".")
        validate_dns_name(normalized, f"service_subdomains.{service}")
        hosts[service] = f"{normalized}.{base_domain}"

    if len(set(hosts.values())) != len(hosts):
        raise ContractError("service_subdomains must generate unique hostnames")

    contract["cluster"]["base_domain"] = base_domain
    contract["hosts"] = hosts
    contract["platform"]["cert_manager"]["acme_email"] = (
        f"{contract['platform']['cert_manager']['acme_email_localpart']}@{base_domain}"
    )
    contract["platform"]["gateway"]["addresses"] = {
        service: str(network[offset])
        for service, offset in SERVICE_ADDRESS_OFFSETS.items()
    }

    authentik_url = f"https://{hosts['authentik']}"
    forgejo_url = f"https://{hosts['forgejo']}"

    forgejo = contract["platform"]["forgejo"]
    forgejo["admin_email"] = f"forgejo@{base_domain}"
    forgejo["root_url"] = f"{forgejo_url}/"
    forgejo["sso"]["authentik_host"] = authentik_url
    forgejo["sso"]["forgejo_root_url"] = forgejo_url
    forgejo["sso"]["discovery_url"] = (
        f"{authentik_url}/application/o/"
        f"{forgejo['sso']['application_slug']}/.well-known/openid-configuration"
    )

    harbor = contract["platform"]["harbor"]
    harbor["host"] = hosts["harbor"]
    harbor["external_url"] = f"https://{hosts['harbor']}"

    stalwart = contract["platform"]["stalwart"]
    stalwart["admin_host"] = hosts["stalwart"]
    stalwart["mail_host"] = hosts["mail"]
    stalwart["public_url"] = f"https://{hosts['stalwart']}"
    stalwart["mail_load_balancer_ip"] = str(network[MAIL_ADDRESS_OFFSET])

    woodpecker = contract["platform"]["woodpecker"]
    woodpecker["host"] = hosts["woodpecker"]
    woodpecker["forgejo_url"] = forgejo_url

    contract["platform"]["velero"]["s3_url"] = f"https://{hosts['minio']}"
    contract["platform"]["observability"]["grafana"]["root_url"] = (
        f"https://{hosts['grafana']}/"
    )
    contract["apps"]["echo"]["host"] = hosts["echo"]

    return contract


def main() -> int:
    try:
        raw_contract = json.load(sys.stdin)
        if not isinstance(raw_contract, dict):
            raise ContractError("environment contract must be a mapping")
        json.dump(materialize_contract(raw_contract), sys.stdout)
        sys.stdout.write("\n")
    except (ContractError, json.JSONDecodeError) as exc:
        print(f"Environment contract materialization failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
