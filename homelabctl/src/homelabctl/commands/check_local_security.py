from __future__ import annotations

import argparse
import stat
from pathlib import Path

from homelabctl.project import ROOT
from homelabctl.runtime import CommandError


def sensitive_local_files(root: Path = ROOT) -> list[Path]:
    paths = [
        root / ".env",
        root / "terraform.tfvars",
        root / "secrets.sops.tfvars",
        root / "out/kubeconfig",
        root / "out/talosconfig",
        root / "out/homelab.effective.yaml",
        root / "test-ssh-git/keys/argocd_test_client_ed25519",
        root / "test-ssh-git/keys/ssh_host_ed25519_key",
        root / "test-ssh-git/keys/ssh_host_rsa_key",
        root / "test-ssh-git/templates/argocd-repository-secret.yaml",
    ]
    for entrypoint in (root / "cluster", root / "infrastructure"):
        paths.extend(entrypoint.glob("*.tfstate*"))
        paths.extend(entrypoint.glob("*.auto.tfvars"))
        paths.extend(entrypoint.glob("*.auto.tfvars.json"))
    return sorted({path for path in paths if path.is_file()})


def insecure_permissions(paths: list[Path]) -> list[tuple[Path, int]]:
    return [
        (path, stat.S_IMODE(path.stat().st_mode))
        for path in paths
        if stat.S_IMODE(path.stat().st_mode) & 0o077
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check local secret and state files without reading their contents."
    )
    parser.add_argument("--fix", action="store_true", help="Set existing files to mode 0600")
    args = parser.parse_args()

    paths = sensitive_local_files()
    if args.fix:
        for path in paths:
            path.chmod(0o600)

    violations = insecure_permissions(paths)
    if violations:
        details = ", ".join(f"{path.relative_to(ROOT)}={mode:04o}" for path, mode in violations)
        raise CommandError(f"local sensitive files must not be group/world-accessible: {details}")

    print(f"[local-security] checked {len(paths)} local sensitive file(s); permissions are 0600")
    return 0
