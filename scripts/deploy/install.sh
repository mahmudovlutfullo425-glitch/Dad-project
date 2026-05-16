#!/usr/bin/env bash
#
# Bootstrap a fresh Ubuntu 24.04 droplet for the flash-sale stack:
#   * Docker Engine + Compose v2 + buildx (official Docker apt repo)
#   * GNU make + git (host-side tools the Makefile uses)
#   * UFW with only 22/80/443 open
#   * docker group membership for the invoking user (so `docker` works
#     without sudo after re-login)
#
# Idempotent: safe to re-run on a half-bootstrapped host. Run as root
# (DigitalOcean default) or with sudo. After it finishes, log out and
# back in once so the new group membership takes effect.
#
# Usage on the droplet:
#   curl -fsSL https://raw.githubusercontent.com/<org>/<repo>/main/scripts/deploy/install.sh | sudo bash
# or, after a `git clone`:
#   sudo bash scripts/deploy/install.sh

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "install.sh: must be run as root (try: sudo bash $0)" >&2
    exit 1
fi

# Resolve the "real" user who invoked sudo so we can add them to the
# docker group. Falls back to root if the script was started directly.
TARGET_USER="${SUDO_USER:-root}"

echo ">>> Updating apt indexes..."
apt-get update -y

echo ">>> Installing prerequisites (ca-certificates, curl, gnupg, ufw, make, git)..."
apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    ufw \
    make \
    git

echo ">>> Adding Docker's official apt repository..."
install -m 0755 -d /etc/apt/keyrings
if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
fi

ARCH="$(dpkg --print-architecture)"
CODENAME="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list

apt-get update -y

echo ">>> Installing Docker Engine + Compose v2..."
apt-get install -y \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin

systemctl enable --now docker

echo ">>> Adding ${TARGET_USER} to docker group..."
if id -nG "${TARGET_USER}" | tr ' ' '\n' | grep -qx docker; then
    echo "    already a member"
else
    usermod -aG docker "${TARGET_USER}"
    echo "    added — re-login as ${TARGET_USER} for the new group to take effect"
fi

echo ">>> Configuring UFW (22 / 80 / 443 only)..."
ufw allow OpenSSH || true
ufw allow 80/tcp || true
ufw allow 443/tcp || true
# --force avoids the interactive y/n on first enable
ufw --force enable

echo ">>> Bumping inet kernel limits for the flash-sale workload..."
# ClickHouse and our k6 viva-demo benefit from a higher fd limit. The
# clickhouse compose service also sets nofile=262144 internally; this
# raises the host-side ceiling so docker's process inherits a reasonable
# value too.
cat > /etc/security/limits.d/99-ecom.conf <<'EOF'
*       soft    nofile  262144
*       hard    nofile  262144
root    soft    nofile  262144
root    hard    nofile  262144
EOF

echo ""
echo "=================================================================="
echo "  Droplet bootstrap complete."
echo ""
echo "  Versions:"
docker --version
docker compose version
echo ""
echo "  Next steps:"
echo "    1. Log out and back in so '${TARGET_USER}' picks up the docker group."
echo "    2. git clone <repo-url>  &&  cd <repo>"
echo "    3. cp .env.example .env  &&  \$EDITOR .env"
echo "         - Set PUBLIC_HOSTNAME to <droplet-ip>.nip.io"
echo "         - Rotate JWT_SECRET, POSTGRES_PASSWORD, MEILI_MASTER_KEY,"
echo "           CLICKHOUSE_PASSWORD to strong values."
echo "         - Set NEXT_PUBLIC_API_URL to https://<droplet-ip>.nip.io/api"
echo "    4. make seed     # migrate + load fixtures"
echo "    5. make up-prod  # boots stack with Caddy auto-TLS on 80/443"
echo "    6. make reindex"
echo "=================================================================="
