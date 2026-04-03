#!/bin/bash
set -e

echo "=================================================="
echo "🚀 AIOps 로컬 환경(On-Premise) 반자동 구축 시작"
echo "=================================================="

echo "[1/5] Tailscale 설치 및 VPN 연결 중..."
if ! command -v tailscale &> /dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
fi
sudo tailscale up --authkey=tskey-auth-kr916asHH521CNTRL-zKtEhr8oXvEroeV3mFs7vEyWSAD5GHcm8 --hostname=aiops-local-worker --accept-routes

LOCAL_TS_IP=$(tailscale ip -4 | head -n 1)
echo "✅ Tailscale 연동 완료! (현재 IP: $LOCAL_TS_IP)"

echo "[2/5] 기본 config.yaml 파일 생성 중 (뼈대 작성)..."
sudo mkdir -p /etc/rancher/k3s
# 🔥 형님이 나중에 수정하기 편하게 기본 뼈대는 확실하게 만들어 둡니다!
sudo bash -c "echo 'tls-san:
  - \"$LOCAL_TS_IP\"
  - \"127.0.0.1\"
write-kubeconfig-mode: \"644\"' > /etc/rancher/k3s/config.yaml"
echo "✅ /etc/rancher/k3s/config.yaml 뼈대 생성 완료!"

echo "[3/5] K3s 클러스터 설치 중..."
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

echo "[4/5] 네임스페이스 및 환경 설정 중..."
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl create namespace boutique-local --dry-run=client -o yaml | sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl apply -f -

echo "[5/5] AWS 리소스 정보 주입 (ConfigMap) 및 앱 배포..."
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl create configmap aws-global-env -n boutique-local \
  --from-literal=AWS_REGION="ap-northeast-2" \
  --from-literal=PROJECT_NAME="Zero-Trust-IDP" \
  --from-literal=LOCAL_TAILSCALE_IP="$LOCAL_TS_IP" \
  --from-literal=AWS_IP="10.10.10.165" \
  --from-literal=FRONTEND_ADDR="aiops-alb-1660575333.ap-northeast-2.elb.amazonaws.com:8080" \
  --from-literal=PRODUCT_CATALOG_SERVICE_ADDR="productcatalogservice:3550" \
  --from-literal=DISABLE_PROFILER="1" \
  --from-literal=DISABLE_TRACING="1" \
  --dry-run=client -o yaml | sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl apply -f -

# 프론트엔드 통신 에러(::1) 방지용 default 네임스페이스 복사본 주입
sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl create configmap aws-global-env -n default \
  --from-literal=LOCAL_TAILSCALE_IP="$LOCAL_TS_IP" \
  --dry-run=client -o yaml | sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl apply -f -

echo "✅ 글로벌 환경변수 주입 완료!"

GITOPS_PATH="/home/ubuntu/Zero-Trust-IDP/gitops/apps/boutique-local"
if [ -d "$GITOPS_PATH" ]; then
    sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl apply -k "$GITOPS_PATH" -n boutique-local
    echo "✅ 로컬 마이크로서비스 배포 완료!"
else
    echo "⚠️ GitOps 경로를 찾을 수 없어 배포를 건너뜁니다: $GITOPS_PATH"
fi

echo "=================================================="
echo "🎉 로컬 기본 환경 세팅 완료!"
echo "👉 [다음 수동 작업 안내]"
echo "1. 로컬 설정 확인: sudo vi /etc/rancher/k3s/config.yaml (수정 시 sudo systemctl restart k3s 실행)"
echo "2. 마스터 노드 접속: ArgoCD 연동은 마스터 노드에서 직접 진행해주세요."
echo "=================================================="