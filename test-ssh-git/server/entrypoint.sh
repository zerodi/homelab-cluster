#!/usr/bin/env bash
set -euo pipefail

GIT_USER="${GIT_USER:-git}"
GIT_HOME="${GIT_HOME:-/home/git}"
SSH_PORT="${SSH_PORT:-2222}"
AUTHORIZED_KEYS_SRC="/config/authorized_keys"
HOST_KEY_ED25519_SRC="/config/ssh_host_ed25519_key"
HOST_KEY_RSA_SRC="/config/ssh_host_rsa_key"

install -d -m 700 -o "$GIT_USER" -g "$GIT_USER" "$GIT_HOME/.ssh"

if [ ! -d "$GIT_HOME/repos" ]; then
  echo "missing git repositories directory: $GIT_HOME/repos" >&2
  exit 1
fi

if [ ! -f "$AUTHORIZED_KEYS_SRC" ]; then
  echo "missing authorized keys: $AUTHORIZED_KEYS_SRC" >&2
  exit 1
fi

install -m 600 -o "$GIT_USER" -g "$GIT_USER" "$AUTHORIZED_KEYS_SRC" "$GIT_HOME/.ssh/authorized_keys"
install -m 600 "$HOST_KEY_ED25519_SRC" /etc/ssh/ssh_host_ed25519_key
install -m 600 "$HOST_KEY_RSA_SRC" /etc/ssh/ssh_host_rsa_key

passwd -u "$GIT_USER" >/dev/null 2>&1 || true
passwd -d "$GIT_USER" >/dev/null 2>&1 || true

cat > /etc/ssh/sshd_config <<CONFIG
Port $SSH_PORT
ListenAddress 0.0.0.0
HostKey /etc/ssh/ssh_host_ed25519_key
HostKey /etc/ssh/ssh_host_rsa_key
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
AllowUsers $GIT_USER
PermitTTY no
AllowTcpForwarding no
X11Forwarding no
Subsystem sftp internal-sftp
PidFile /var/run/sshd.pid
LogLevel VERBOSE
CONFIG

chown "$GIT_USER:$GIT_USER" "$GIT_HOME"
chown -R "$GIT_USER:$GIT_USER" "$GIT_HOME/.ssh"
exec /usr/sbin/sshd -D -e
