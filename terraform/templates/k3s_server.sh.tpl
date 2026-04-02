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
  curl nfs-common ca-certificates apt-transport-https jq awscli

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
# 4. K3s Server 설치 (방화벽 및 TLS SAN 자동 등록)
# ---------------------------------------------------------
ufw allow 6443/tcp || true
ufw allow in on tailscale0 || true

PRIVATE_IP=$(hostname -I | awk '{print $1}')
TS_IP=$(tailscale ip -4 || true)

if [ ! -f /etc/rancher/k3s/k3s.yaml ]; then
  curl -sfL https://get.k3s.io | \
    INSTALL_K3S_VERSION="$K3S_VERSION" \
    INSTALL_K3S_EXEC="server --write-kubeconfig-mode 644 --disable traefik --tls-san $PRIVATE_IP --tls-san $TS_IP" \
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

echo "기다리는 중... K3s API가 준비될 때까지"
until /usr/local/bin/kubectl get nodes; do
  sleep 5
done

# ---------------------------------------------------------
# 6. GitHub dispatch token secret bootstrap
# ---------------------------------------------------------
echo "[INFO] ensuring kafka-poc namespace exists"
kubectl get namespace kafka-poc >/dev/null 2>&1 || kubectl create namespace kafka-poc

echo "[INFO] reading GitHub dispatch token from SSM"
GITHUB_DISPATCH_TOKEN="$(aws ssm get-parameter \
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
# 7. 마스터 노드 라벨 수동 추가 (보안 정책 회피)
# ---------------------------------------------------------
echo "마스터 노드 라벨링 중..."
/usr/local/bin/kubectl label node "$(hostname)" node-role.kubernetes.io/master=true kubernetes.io/role=master --overwrite

# ---------------------------------------------------------
# 8. configmap 생성 (글로벌 환경변수 전달)
# ---------------------------------------------------------
echo "글로벌 환경변수 ConfigMap 생성 중..."
/usr/local/bin/kubectl create configmap aws-global-env \
  --from-literal=AWS_REGION="ap-northeast-2" \
  --from-literal=PROJECT_NAME="${project_name}" \
  --from-literal=ENVIRONMENT="production" \
  --from-literal=LOCAL_TAILSCALE_IP="${local_tailscale_ip}" \
  --from-literal=AWS_IP="$(hostname -I | awk '{print $1}')" \
  --from-literal=FRONTEND_ADDR="${frontend_addr}" \
  -n default --dry-run=client -o yaml | /usr/local/bin/kubectl apply -f -

echo "✅ ConfigMap 생성 완료!"

# ---------------------------------------------------------
# 9. 워커 노드 자동 라벨링 백그라운드 루프
# ---------------------------------------------------------
cat <<'EOF' > /usr/local/bin/auto-label-workers.sh
#!/bin/bash
while true; do
  NODES=$(/usr/local/bin/kubectl get nodes --no-headers | grep '<none>' | awk '{print $1}')
  for NODE in $NODES; do
    if [[ $NODE == ip-10-10-20-* ]]; then
      /usr/local/bin/kubectl label node $NODE node-role.kubernetes.io/worker=true kubernetes.io/role=worker --overwrite
      echo "✅ 노드 $NODE 에 워커 라벨을 자동으로 붙였습니다."
    fi
  done
  sleep 30
done
EOF

chmod +x /usr/local/bin/auto-label-workers.sh
nohup /usr/local/bin/auto-label-workers.sh > /var/log/k3s-auto-label.log 2>&1 &

# ---------------------------------------------------------
# 10. ArgoCD CLI 자동 설치
# ---------------------------------------------------------
echo "Installing ArgoCD CLI..."
curl -sSL -o argocd-linux-amd64 https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
sudo install -m 555 argocd-linux-amd64 /usr/local/bin/argocd
rm -f argocd-linux-amd64
echo "ArgoCD CLI installation complete."

# ---------------------------------------------------------
# 11. ArgoCD 서버 Insecure 모드 설정 (ALB 연동 필수)
# ---------------------------------------------------------
echo "ArgoCD 서버를 ALB용 Insecure 모드로 전환 중..."
if /usr/local/bin/kubectl get namespace argocd >/dev/null 2>&1; then
  /usr/local/bin/kubectl patch cm argocd-cmd-params-cm -n argocd \
    -p '{"data": {"server.insecure": "true"}}' || true

  /usr/local/bin/kubectl rollout restart deployment argocd-server -n argocd || true

  echo "ArgoCD 서버 재시작 대기 중..."
  /usr/local/bin/kubectl rollout status deployment argocd-server -n argocd --timeout=60s || true
else
  echo "[WARN] argocd namespace not found. skipping argocd insecure patch."
fi

echo "[INFO] k3s server bootstrap completed."