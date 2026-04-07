#!/bin/bash
set -euxo pipefail

LOG_FILE="/var/log/k3s-agent-bootstrap.log"
exec > >(tee -a "$LOG_FILE") 2>&1

TAILSCALE_AUTH_KEY="${tailscale_auth_key}"
K3S_TOKEN="${k3s_token}"
K3S_SERVER_IP="${k3s_server_ip}"

# ---------------------------------------------------------
# 1. 공통 준비
# ---------------------------------------------------------
if ! swapon --show | grep -q "/swapfile"; then
  if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile
  fi
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y \
  curl \
  jq \
  awscli \
  nfs-common \
  ca-certificates \
  apt-transport-https

# ---------------------------------------------------------
# 2. SSM Agent
# ---------------------------------------------------------
if ! snap list | grep -q amazon-ssm-agent; then
  snap install amazon-ssm-agent --classic || true
fi

# snap 기반 환경에서는 systemctl 서비스명이 다를 수 있으므로 강제 실패시키지 않음
snap services amazon-ssm-agent || true
systemctl daemon-reload || true

# ---------------------------------------------------------
# 3. Tailscale
# ---------------------------------------------------------
if [ -n "$${TAILSCALE_AUTH_KEY:-}" ]; then
  if ! command -v tailscale >/dev/null 2>&1; then
    curl -fsSL https://tailscale.com/install.sh | sh
  fi
  systemctl enable tailscaled
  systemctl restart tailscaled
  tailscale up --authkey "$${TAILSCALE_AUTH_KEY}" || true
fi

# ---------------------------------------------------------
# 4. K3s Agent Join
# ---------------------------------------------------------
echo "[INFO] joining worker to k3s cluster"

curl -sfL https://get.k3s.io | \
  INSTALL_K3S_VERSION="v1.33.9+k3s1" \
  K3S_URL="https://$${K3S_SERVER_IP}:6443" \
  K3S_TOKEN="$${K3S_TOKEN}" \
  sh -

systemctl enable k3s-agent
systemctl restart k3s-agent

echo "[INFO] k3s agent join completed."