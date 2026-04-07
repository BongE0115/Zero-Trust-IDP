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

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y \
  curl \
  nfs-common \
  ca-certificates \
  apt-transport-https \
  jq \
  awscli

# ---------------------------------------------------------
# 2. SSM Agent 보장
# ---------------------------------------------------------
if ! snap list | grep -q amazon-ssm-agent; then
  snap install amazon-ssm-agent --classic || true
fi

snap services amazon-ssm-agent || true
systemctl daemon-reload || true

# ---------------------------------------------------------
# 3. Tailscale 설치
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
# 4. K3s Server 설치
# ---------------------------------------------------------
ufw allow 6443/tcp || true
ufw allow in on tailscale0 || true

PRIVATE_IP="$$(hostname -I | awk '{print $1}')"
TS_IP="$$(tailscale ip -4 2>/dev/null || true)"

if [ ! -f /etc/rancher/k3s/k3s.yaml ]; then
  curl -sfL https://get.k3s.io | \
    INSTALL_K3S_VERSION="$${K3S_VERSION}" \
    INSTALL_K3S_EXEC="server --write-kubeconfig-mode 644 --disable traefik --tls-san $${PRIVATE_IP} $$( [ -n "$${TS_IP}" ] && printf '%s' "--tls-san $${TS_IP}" )" \
    K3S_TOKEN="$${K3S_TOKEN}" \
    sh -
fi

# ---------------------------------------------------------
# 5. K3s readiness 대기 및 kubeconfig 접속 주소 수정
# ---------------------------------------------------------
for i in {1..40}; do
  if [ -f /etc/rancher/k3s/k3s.yaml ]; then
    break
  fi
  sleep 10
done

if command -v tailscale >/dev/null 2>&1; then
  MASTER_TS_IP="$$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
else
  MASTER_TS_IP=""
fi

if [ -n "$${MASTER_TS_IP}" ] && [ -f /etc/rancher/k3s/k3s.yaml ]; then
  sed -i "s/127.0.0.1/$${MASTER_TS_IP}/g" /etc/rancher/k3s/k3s.yaml
fi

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

for i in {1..40}; do
  if kubectl get nodes >/dev/null 2>&1; then
    echo "[INFO] Kubernetes API is ready."
    break
  fi
  echo "[INFO] Waiting for Kubernetes API... ($${i}/40)"
  sleep 15
done

# ---------------------------------------------------------
# 6. GitHub dispatch token secret bootstrap
# ---------------------------------------------------------
echo "[INFO] ensuring kafka-poc namespace exists"
kubectl get namespace kafka-poc >/dev/null 2>&1 || kubectl create namespace kafka-poc

echo "[INFO] reading GitHub dispatch token from SSM"
GITHUB_DISPATCH_TOKEN="$$(aws ssm get-parameter \
  --name "/zero-trust-idp/github-dispatch-token" \
  --with-decryption \
  --query "Parameter.Value" \
  --output text \
  --region ap-northeast-2)"

if [ -z "$${GITHUB_DISPATCH_TOKEN}" ] || [ "$${GITHUB_DISPATCH_TOKEN}" = "None" ]; then
  echo "[ERROR] failed to read github dispatch token from SSM"
  exit 1
fi

echo "[INFO] applying github-dispatch-secret"
kubectl -n kafka-poc create secret generic github-dispatch-secret \
  --from-literal=token="$${GITHUB_DISPATCH_TOKEN}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "[INFO] github-dispatch-secret applied successfully"

# ---------------------------------------------------------
# 7. 마스터 노드 라벨 추가
# ---------------------------------------------------------
echo "[INFO] labeling master node"
/usr/local/bin/kubectl label node "$$(hostname)" \
  node-role.kubernetes.io/master=true \
  kubernetes.io/role=master \
  --overwrite

# ---------------------------------------------------------
# 8. 글로벌 ConfigMap 생성
# ---------------------------------------------------------
echo "[INFO] creating aws-global-env configmap"
/usr/local/bin/kubectl create configmap aws-global-env \
  --from-literal=AWS_REGION="ap-northeast-2" \
  --from-literal=PROJECT_NAME="${project_name}" \
  --from-literal=ENVIRONMENT="production" \
  --from-literal=LOCAL_TAILSCALE_IP="${local_tailscale_ip}" \
  --from-literal=AWS_IP="$$(hostname -I | awk '{print $1}')" \
  --from-literal=FRONTEND_ADDR="${frontend_addr}" \
  -n default --dry-run=client -o yaml | /usr/local/bin/kubectl apply -f -

echo "[INFO] aws-global-env configmap created"

# ---------------------------------------------------------
# 9. 워커 자동 라벨링 루프
# ---------------------------------------------------------
cat <<'EOF' > /usr/local/bin/auto-label-workers.sh
#!/bin/bash
set -eu

while true; do
  NODES=$(/usr/local/bin/kubectl get nodes --no-headers 2>/dev/null | awk '$2 != "Ready" || $3 == "<none>" {print $1}')
  for NODE in $NODES; do
    if [[ "$NODE" == ip-10-10-20-* ]]; then
      /usr/local/bin/kubectl label node "$NODE" node-role.kubernetes.io/worker=true kubernetes.io/role=worker --overwrite || true
      echo "worker label applied to $NODE"
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
echo "[INFO] installing ArgoCD CLI"
curl -sSL -o /tmp/argocd-linux-amd64 \
  https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
install -m 555 /tmp/argocd-linux-amd64 /usr/local/bin/argocd
rm -f /tmp/argocd-linux-amd64
echo "[INFO] ArgoCD CLI installation complete"

# ---------------------------------------------------------
# 11. ArgoCD insecure 모드 패치
# ---------------------------------------------------------
echo "[INFO] patching ArgoCD insecure mode if namespace exists"
if /usr/local/bin/kubectl get namespace argocd >/dev/null 2>&1; then
  /usr/local/bin/kubectl patch cm argocd-cmd-params-cm -n argocd \
    -p '{"data":{"server.insecure":"true"}}' || true

  /usr/local/bin/kubectl rollout restart deployment argocd-server -n argocd || true
  /usr/local/bin/kubectl rollout status deployment argocd-server -n argocd --timeout=60s || true
else
  echo "[WARN] argocd namespace not found. skipping argocd insecure patch."
fi

echo "[INFO] k3s server bootstrap completed."

# =========================================================
# 12. K3s 기동 확인 후 Slack Secret 생성
# =========================================================
echo "[INFO] waiting for K3s to be ready"
until k3s kubectl get node >/dev/null 2>&1; do
  sleep 5
done

k3s kubectl create namespace kafka-poc --dry-run=client -o yaml | k3s kubectl apply -f -

k3s kubectl create secret generic slack-credentials \
  --namespace=kafka-poc \
  --from-literal=SLACK_BOT_TOKEN="${slack_bot_token}" \
  --from-literal=SLACK_CHANNEL="${slack_channel}" \
  --dry-run=client -o yaml | k3s kubectl apply -f -

echo "[INFO] Slack credentials secret created successfully"