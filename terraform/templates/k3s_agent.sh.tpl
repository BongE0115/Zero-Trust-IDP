#!/bin/bash
set -euxo pipefail

LOG_FILE="/var/log/k3s-agent-bootstrap.log"
exec > >(tee -a "$LOG_FILE") 2>&1

TAILSCALE_AUTH_KEY="${tailscale_auth_key}"

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
# 2. SSM Agent 보장
# ---------------------------------------------------------
if ! systemctl list-unit-files | grep -q amazon-ssm-agent; then
  snap install amazon-ssm-agent --classic || true
fi

systemctl enable amazon-ssm-agent || true
systemctl restart amazon-ssm-agent || true

# ---------------------------------------------------------
# 3. Tailscale 설치
# ---------------------------------------------------------
if [ -n "${TAILSCALE_AUTH_KEY}" ]; then
  if ! command -v tailscale >/dev/null 2>&1; then
    curl -fsSL https://tailscale.com/install.sh | sh
  fi
  systemctl enable tailscaled
  systemctl restart tailscaled
  tailscale up --authkey "${TAILSCALE_AUTH_KEY}" || true
fi

echo "[INFO] k3s agent base bootstrap completed."