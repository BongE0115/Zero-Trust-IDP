#!/bin/bash
set -e

echo "=================================================="
echo "🚀 AIOps 로컬 환경(On-Premise) 자동 구축 시작"
echo "=================================================="

echo "[1/6] Tailscale 설치 및 VPN 연결 중..."
if ! command -v tailscale &> /dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
fi
sudo tailscale up --authkey=tskey-auth-kr916asHH521CNTRL-zKtEhr8oXvEroeV3mFs7vEyWSAD5GHcm8 --hostname=aiops-local-worker --accept-routes

LOCAL_TS_IP=$(tailscale ip -4 | head -n 1)
echo "✅ Tailscale 연동 완료! (현재 IP: $LOCAL_TS_IP)"

echo "[2/6] K3s 클러스터 설치 중..."
sudo mkdir -p /etc/rancher/k3s
sudo bash -c "echo 'tls-san:
  - \"$LOCAL_TS_IP\"
  - \"127.0.0.1\"
write-kubeconfig-mode: \"644\"' > /etc/rancher/k3s/config.yaml"

if ! command -v k3s &> /dev/null; then
    curl -sfL https://get.k3s.io | sh -
else
    sudo systemctl restart k3s
fi

echo "⏳ K3s API 서버 시작 및 Kubeconfig 파일 생성 대기 중..."
for i in {1..30}; do
    if [ -f /etc/rancher/k3s/k3s.yaml ]; then
        echo "✅ Kubeconfig 파일 생성 확인!"
        break
    fi
    sleep 2
done
sleep 5

echo "[3/6] 네임스페이스 및 환경 설정 중..."
# K3s 설정 파일은 root 소유이므로 sudo와 함께 실행
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl create namespace boutique-local --dry-run=client -o yaml | sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl apply -f -

echo "[4/6] AWS 리소스 정보 주입 (ConfigMap)..."
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl create configmap aws-global-env -n boutique-local \
  --from-literal=AWS_REGION="ap-northeast-2" \
  --from-literal=PROJECT_NAME="Zero-Trust-IDP" \
  --from-literal=LOCAL_TAILSCALE_IP="" \
  --from-literal=AWS_IP="10.10.10.113" \
  --from-literal=FRONTEND_ADDR="aiops-alb-1972997103.ap-northeast-2.elb.amazonaws.com:8080" \
  --from-literal=PRODUCT_CATALOG_SERVICE_ADDR="productcatalogservice:3550" \
  --from-literal=DISABLE_PROFILER="1" \
  --from-literal=DISABLE_TRACING="1" \
  --dry-run=client -o yaml | sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl apply -f -
echo "✅ 글로벌 환경변수 주입 완료!"

echo "[5/6] 로컬 전용 마이크로서비스 배포..."
GITOPS_PATH="/home/ubuntu/Zero-Trust-IDP/gitops/apps/boutique-local"
if [ -d "$GITOPS_PATH" ]; then
    sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl apply -k "$GITOPS_PATH" -n boutique-local
    echo "✅ 로컬 마이크로서비스 배포 완료!"
else
    echo "⚠️ GitOps 경로를 찾을 수 없어 배포를 건너뜁니다: $GITOPS_PATH"
fi

echo "[6/6] 🤖 AWS SSM을 통해 마스터 노드의 ArgoCD 자동 연동을 시작합니다..."
    
# Kubeconfig 읽을 때 sudo 사용
LOCAL_KUBECONFIG_B64=$(sudo cat /etc/rancher/k3s/k3s.yaml | sed "s/127.0.0.1/$LOCAL_TS_IP/g" | base64 -w 0)
MASTER_INSTANCE_ID="i-07a35fc1b35019bef"
AWS_REGION="ap-northeast-2"

# aws ssm 명령어는 sudo 없이 현재 사용자 권한으로 실행 (인증 유지)
aws ssm send-command \
  --region "$AWS_REGION" \
  --instance-ids "$MASTER_INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters commands='[
    "#!/bin/bash",
    "set -e",
    "echo \"ArgoCD 서버 준비 대기 중...\"",
    "sleep 30",
    "echo '"$LOCAL_KUBECONFIG_B64"' | base64 -d > /tmp/local-cluster.yaml",
    "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml",
    "ARGOCD_PW=\$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath=\"{.data.password}\" | base64 -d)",
    "argocd login localhost:30080 --username admin --password \$ARGOCD_PW --plaintext",
    "argocd cluster add default --name boutique-local-cluster --kubeconfig /tmp/local-cluster.yaml --yes || true",
    "kubectl patch application boutique-local -n argocd --type=\"json\" -p=\"[{\\\"op\\\": \\\"replace\\\", \\\"path\\\": \\\"/spec/destination\\\", \\\"value\\\": {\\\"name\\\": \\\"boutique-local-cluster\\\", \\\"namespace\\\": \\\"boutique-local\\\"}}]\"",
    "argocd app set boutique-local --sync-policy automated --auto-prune --self-heal --sync-option CreateNamespace=true",
    "argocd app sync boutique-local || true",
    "echo \"ArgoCD 연동 및 패치 완료!\""
  ]'

echo "=================================================="
echo "🎉 로컬 환경 세팅 및 GitOps 하이브리드 자동화 완벽 종료!"
echo "=================================================="
