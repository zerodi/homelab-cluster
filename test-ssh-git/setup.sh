#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
KEY_DIR="$ROOT_DIR/keys"
TEMPLATE_DIR="$ROOT_DIR/templates"
REPO_DIR="$ROOT_DIR/repo-data/gitops.git"
ARGOCD_DIR="$PROJECT_ROOT/argocd"
CLIENT_KEY="$KEY_DIR/argocd_test_client_ed25519"
SERVER_HOSTNAME="${SERVER_HOSTNAME:-git.localtest.me}"
SERVER_PORT="${SERVER_PORT:-2222}"
REPO_URL="ssh://git@${SERVER_HOSTNAME}:${SERVER_PORT}/home/git/repos/gitops.git"
PLACEHOLDER_REPO_URL="https://git.example.invalid/replace-me/gitops.git"

mkdir -p "$KEY_DIR" "$TEMPLATE_DIR" "$ROOT_DIR/repo-data"

if [ ! -f "$CLIENT_KEY" ]; then
  ssh-keygen -t ed25519 -N '' -f "$CLIENT_KEY" -C 'argocd-test-client' >/dev/null
fi

if [ ! -f "$KEY_DIR/ssh_host_ed25519_key" ]; then
  ssh-keygen -t ed25519 -N '' -f "$KEY_DIR/ssh_host_ed25519_key" -C 'argocd-test-host' >/dev/null
fi

if [ ! -f "$KEY_DIR/ssh_host_rsa_key" ]; then
  ssh-keygen -t rsa -b 4096 -N '' -f "$KEY_DIR/ssh_host_rsa_key" -C 'argocd-test-host-rsa' >/dev/null
fi

cp "$CLIENT_KEY.pub" "$KEY_DIR/authorized_keys"
chmod 600 "$KEY_DIR/authorized_keys" "$CLIENT_KEY" "$KEY_DIR/ssh_host_ed25519_key" "$KEY_DIR/ssh_host_rsa_key"
chmod 644 "$CLIENT_KEY.pub" "$KEY_DIR/ssh_host_ed25519_key.pub" "$KEY_DIR/ssh_host_rsa_key.pub"

rm -rf "$REPO_DIR"
WORKTREE_DIR="$(mktemp -d)"
trap 'rm -rf "$WORKTREE_DIR" "$ROOT_DIR/.seed"' EXIT
mkdir -p "$WORKTREE_DIR"
cp -R "$ARGOCD_DIR/bootstrap" "$WORKTREE_DIR/"
cp -R "$ARGOCD_DIR/platform" "$WORKTREE_DIR/"
cp -R "$ARGOCD_DIR/apps" "$WORKTREE_DIR/"
cp "$ARGOCD_DIR/README.md" "$WORKTREE_DIR/README.md"
find "$WORKTREE_DIR" -type f \( -name '*.yaml' -o -name '*.yml' \) -exec sed -i "s#${PLACEHOLDER_REPO_URL}#${REPO_URL}#g" {} +

git init --bare "$REPO_DIR" >/dev/null
git -C "$REPO_DIR" symbolic-ref HEAD refs/heads/main
TMP_REPO="$ROOT_DIR/.seed"
rm -rf "$TMP_REPO"
git init "$TMP_REPO" >/dev/null
(
  cd "$TMP_REPO"
  cp -R "$WORKTREE_DIR/." .
  git add .
  git -c user.name='argocd-test' -c user.email='argocd-test@example.invalid' commit -m 'Initial GitOps scaffold' >/dev/null
  git branch -M main
  git remote add origin "$REPO_DIR"
  git push origin main >/dev/null
)

{
  printf '[%s]:%s ' "$SERVER_HOSTNAME" "$SERVER_PORT"
  cat "$KEY_DIR/ssh_host_ed25519_key.pub"
  printf '[%s]:%s ' "$SERVER_HOSTNAME" "$SERVER_PORT"
  cat "$KEY_DIR/ssh_host_rsa_key.pub"
} > "$KEY_DIR/known_hosts"

cat > "$TEMPLATE_DIR/argocd-repository-secret.yaml" <<TEMPLATE
apiVersion: v1
kind: Secret
metadata:
  name: test-ssh-gitops-repo
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  type: git
  url: $REPO_URL
  name: test-ssh-gitops
  sshPrivateKey: |
$(sed 's/^/    /' "$CLIENT_KEY")
  insecure: "false"
TEMPLATE

cat > "$TEMPLATE_DIR/root-application-ssh.yaml" <<TEMPLATE
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: root-ssh
  namespace: argocd
spec:
  project: default
  source:
    repoURL: $REPO_URL
    targetRevision: main
    path: bootstrap
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
TEMPLATE

cat <<INFO
Test SSH Git server prepared.

Repo URL:
  $REPO_URL

Client private key:
  $CLIENT_KEY

Known hosts:
  $KEY_DIR/known_hosts

Generated manifests:
  $TEMPLATE_DIR/argocd-repository-secret.yaml
  $TEMPLATE_DIR/root-application-ssh.yaml

Seeded GitOps content:
  bootstrap/
  platform/
  apps/
  README.md

The seeded GitOps tree has all placeholder repo URLs rewritten to:
  $REPO_URL

Next steps:
  1. cd $ROOT_DIR && docker compose up -d --build
  2. kubectl -n argocd create configmap argocd-ssh-known-hosts-cm \
       --from-file=ssh_known_hosts=$KEY_DIR/known_hosts \
       -o yaml --dry-run=client | kubectl apply -f -
  3. kubectl apply -f $TEMPLATE_DIR/argocd-repository-secret.yaml
  4. kubectl apply -f $TEMPLATE_DIR/root-application-ssh.yaml
INFO
