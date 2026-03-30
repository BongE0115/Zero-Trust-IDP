#!/bin/bash
set -euxo pipefail

LOG_FILE="/var/log/k3s-server-bootstrap.log"
exec > >(tee -a "$LOG_FILE") 2>&1

K3S_VERSION="v1.33.9+k3s1"
K3S_TOKEN="${k3s_token}"
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

apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  curl nfs-common ca-certificates apt-transport-https jq

# ---------------------------------------------------------
# 2. SSM Agent 보장
# ---------------------------------------------------------
if ! systemctl list-unit-files | grep -q amazon-ssm-agent; then
  snap install amazon-ssm-agent --classic || true
fi
systemctl enable amazon-ssm-agent || true
systemctl restart amazon-ssm-agent || true

# ---------------------------------------------------------
# 3. Tailscale 설치 (기존 구조 유지 시)
# ---------------------------------------------------------
if [ -n "$TAILSCALE_AUTH_KEY" ]; then
  curl -fsSL https://tailscale.com/install.sh | sh
  systemctl enable tailscaled
  systemctl restart tailscaled
  tailscale up --authkey "$TAILSCALE_AUTH_KEY" || true
fi

# ---------------------------------------------------------
# 4. K3s Server 설치
# ---------------------------------------------------------
if [ ! -f /etc/rancher/k3s/k3s.yaml ]; then
  curl -sfL https://get.k3s.io | \
    INSTALL_K3S_VERSION="$K3S_VERSION" \
    INSTALL_K3S_EXEC="server --write-kubeconfig-mode 644 --disable traefik" \
    K3S_TOKEN="$K3S_TOKEN" sh -
fi

# ---------------------------------------------------------
# 5. K3s readiness 대기
# ---------------------------------------------------------
for i in {1..40}; do
  if [ -f /etc/rancher/k3s/k3s.yaml ]; then
    break
  fi
  sleep 10
done

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

for i in {1..40}; do
  if kubectl get nodes >/dev/null 2>&1; then
    echo "[INFO] Kubernetes API is ready."
    break
  fi
  echo "[INFO] Waiting for Kubernetes API... ($i/40)"
  sleep 15
done

kubectl get nodes || true

echo "[INFO] k3s server bootstrap completed."