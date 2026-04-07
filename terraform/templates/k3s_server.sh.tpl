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
  curl nfs-common ca-certificates apt-transport-https jq awscli ufw

# ---------------------------------------------------------
# 2. SSM Agent 보장
# ---------------------------------------------------------
if ! systemctl list-unit-files | grep -q amazon-ssm-agent; then
  snap install amazon-ssm-agent --classic || true
fi
systemctl enable amazon-ssm-agent || true
systemctl restart amazon-ssm-agent || true

# ---------------------------------------------------------
# 3. Tailscale 설치 (옵션)
# ---------------------------------------------------------
TS_IP=""
if [ -n "$TAILSCALE_AUTH_KEY" ]; then
  curl -fsSL https://tailscale.com/install.sh | sh
  systemctl enable tailscaled
  systemctl restart tailscaled
  tailscale up --authkey "$TAILSCALE_AUTH_KEY" || true
  TS_IP="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
fi

# ---------------------------------------------------------
# 4. K3s Server 설치
# ---------------------------------------------------------
ufw allow 6443/tcp || true
if [ -n "$TS_IP" ]; then
  ufw allow in on tailscale0 || true
fi

PRIVATE_IP="$(hostname -I | awk '{print $1}')"

INSTALL_K3S_EXEC_ARGS="server --write-kubeconfig-mode 644 --disable traefik --tls-san ${PRIVATE_IP}"
if [ -n "$TS_IP" ]; then
  INSTALL_K3S_EXEC_ARGS="${INSTALL_K3S_EXEC_ARGS} --tls-san ${TS_IP}"
fi

if [ ! -f /etc/rancher/k3s/k3s.yaml ]; then
  curl -sfL https://get.k3s.io | \
    INSTALL_K3S_VERSION="$K3S_VERSION" \
    INSTALL_K3S_EXEC="$INSTALL_K3S_EXEC_ARGS" \
    K3S_TOKEN="$K3S_TOKEN" \
    sh -
fi

# ---------------------------------------------------------
# 5. K3s readiness 대기 및 kubeconfig 정리
# ---------------------------------------------------------
for i in {1..40}; do
  if [ -f /etc/rancher/k3s/k3s.yaml ]; then
    break
  fi
  echo "[INFO] Waiting for /etc/rancher/k3s/k3s.yaml ... ($i/40)"
  sleep 10
done

if [ ! -f /etc/rancher/k3s/k3s.yaml ]; then
  echo "[ERROR] k3s kubeconfig not found after waiting."
  exit 1
fi

if [ -n "$TS_IP" ]; then
  sed -i "s/127.0.0.1/${TS_IP}/g" /etc/rancher/k3s/k3s.yaml
else
  sed -i "s/127.0.0.1/${PRIVATE_IP}/g" /etc/rancher/k3s/k3s.yaml
fi

chmod 644 /etc/rancher/k3s/k3s.yaml
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

for i in {1..40}; do
  if k3s kubectl get nodes >/dev/null 2>&1; then
    echo "[INFO] Kubernetes API is ready."
    break
  fi
  echo "[INFO] Waiting for Kubernetes API... ($i/40)"
  sleep 15
done

if ! k3s kubectl get nodes >/dev/null 2>&1; then
  echo "[ERROR] Kubernetes API did not become ready in time."
  exit 1
fi

# ---------------------------------------------------------
# 6. GitHub dispatch token secret bootstrap
# ---------------------------------------------------------
echo "[INFO] ensuring kafka-poc namespace exists"
k3s kubectl get namespace kafka-poc >/dev/null 2>&1 || k3s kubectl create namespace kafka-poc

echo "[INFO] reading GitHub dispatch token from SSM"
GITHUB_DISPATCH_TOKEN="$(aws ssm get-parameter \
  --name "/zero-trust-idp/github-dispatch-token" \
  --with-decryption \
  --query "Parameter.Value" \
  --output text \
  --region ap-northeast-2)"

if [ -z "${GITHUB_DISPATCH_TOKEN}" ] || [ "${GITHUB_DISPATCH_TOKEN}" = "None" ]; then
  echo "[ERROR] failed to read github dispatch token from SSM"
  exit 1
fi

echo "[INFO] applying github-dispatch-secret"
k3s kubectl -n kafka-poc create secret generic github-dispatch-secret \
  --from-literal=token="${GITHUB_DISPATCH_TOKEN}" \
  --dry-run=client -o yaml | k3s kubectl apply -f -

echo "[INFO] github-dispatch-secret applied successfully"

# ---------------------------------------------------------
# 7. 마스터 노드 라벨 추가
# ---------------------------------------------------------
echo "[INFO] labeling master node..."
k3s kubectl label node "$(hostname)" \
  node-role.kubernetes.io/master=true \
  kubernetes.io/role=master \
  --overwrite || true

# ---------------------------------------------------------
# 8. 글로벌 환경변수 ConfigMap 생성
# ---------------------------------------------------------
echo "[INFO] creating aws-global-env ConfigMap..."
k3s kubectl create configmap aws-global-env \
  --from-literal=AWS_REGION="ap-northeast-2" \
  --from-literal=PROJECT_NAME="${project_name}" \
  --from-literal=ENVIRONMENT="production" \
  --from-literal=LOCAL_TAILSCALE_IP="${local_tailscale_ip}" \
  --from-literal=AWS_IP="${PRIVATE_IP}" \
  --from-literal=FRONTEND_ADDR="${frontend_addr}" \
  -n default \
  --dry-run=client -o yaml | k3s kubectl apply -f -

echo "[INFO] aws-global-env ConfigMap applied."

# ---------------------------------------------------------
# 9. 워커 노드 자동 라벨링 백그라운드 루프
# ---------------------------------------------------------
cat <<'EOF' > /usr/local/bin/auto-label-workers.sh
#!/bin/bash
set -euo pipefail

while true; do
  NODES=$(/usr/local/bin/k3s kubectl get nodes --no-headers | awk '$3 == "<none>" {print $1}')
  for NODE in $NODES; do
    if [[ "$NODE" == ip-10-10-20-* ]]; then
      /usr/local/bin/k3s kubectl label node "$NODE" \
        node-role.kubernetes.io/worker=true \
        kubernetes.io/role=worker \
        --overwrite
      echo "✅ 노드 $NODE 에 워커 라벨을 자동으로 붙였습니다."
    fi
  done
  sleep 30
done
EOF

chmod +x /usr/local/bin/auto-label-workers.sh
nohup /usr/local/bin/auto-label-workers.sh > /var/log/k3s-auto-label.log 2>&1 &

# ---------------------------------------------------------
# 10. ArgoCD CLI 설치
# ---------------------------------------------------------
echo "[INFO] Installing ArgoCD CLI..."
curl -sSL -o /tmp/argocd-linux-amd64 \
  https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
install -m 555 /tmp/argocd-linux-amd64 /usr/local/bin/argocd
rm -f /tmp/argocd-linux-amd64
echo "[INFO] ArgoCD CLI installation complete."

# ---------------------------------------------------------
# 11. Slack Secret 생성
# ---------------------------------------------------------
echo "[INFO] applying slack-credentials secret..."
k3s kubectl create namespace kafka-poc --dry-run=client -o yaml | k3s kubectl apply -f -

k3s kubectl create secret generic slack-credentials \
  --namespace=kafka-poc \
  --from-literal=SLACK_BOT_TOKEN="${slack_bot_token}" \
  --from-literal=SLACK_CHANNEL="${slack_channel}" \
  --dry-run=client -o yaml | k3s kubectl apply -f -

echo "[INFO] Slack credentials secret applied successfully."
echo "[INFO] k3s server bootstrap completed."