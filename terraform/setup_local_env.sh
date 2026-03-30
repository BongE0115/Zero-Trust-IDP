#!/bin/bash
set -e

echo "=================================================="
echo "🚀 AIOps 로컬 환경(On-Premise) 자동 구축 스크립트"
echo "=================================================="

echo "[1/5] Tailscale 설치 및 AWS 망(VPN) 조인 진행 중..."
curl -fsSL https://tailscale.com/install.sh | sh
# 테라폼 변수로 입력받은 Tailscale Auth Key를 그대로 주입합니다.
sudo tailscale up --authkey=tskey-auth-kr916asHH521CNTRL-zKtEhr8oXvEroeV3mFs7vEyWSAD5GHcm8 --hostname=aiops-local-worker
echo "✅ Tailscale 연동 완료! (로컬 ↔ AWS 터널링 성공)"

echo "[2/5] 로컬 K3s 클러스터 설치 진행 중..."
# 로컬은 마스터/워커 구분 없이 단일 클러스터로 가볍게 띄웁니다.
curl -sfL https://get.k3s.io | sh -
echo "✅ 로컬 K3s 설치 완료!"

echo "[3/5] Kubeconfig 권한 설정 및 네임스페이스 생성..."
sudo chmod 644 /etc/rancher/k3s/k3s.yaml
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
    
# K3s가 완전히 뜰 때까지 잠시 대기
sleep 10 
    
kubectl create namespace boutique-local --dry-run=client -o yaml | kubectl apply -f -
echo "✅ boutique-local 네임스페이스 생성 완료!"

# 🔥 추가된 마법: 테라폼이 생성한 ALB 주소를 로컬 K3s ConfigMap으로 주입
echo "[4/5] AWS ALB 주소를 로컬 환경변수(ConfigMap)로 주입합니다..."
kubectl create configmap aws-global-env -n boutique-local \
  --from-literal=AWS_REGION=ap-northeast-2 \
  --from-literal=PROJECT_NAME=Zero-Trust-IDP \
  --from-literal=LOCAL_TAILSCALE_IP=100.127.40.114 \
  --from-literal=AWS_IP=100.88.181.49 \
  --from-literal=FRONTEND_ADDR=100.88.181.49:30081 \
  --from-literal=PRODUCT_CATALOG_SERVICE_ADDR=productcatalogservice:3550 \
  --from-literal=DISABLE_PROFILER=1 \
  --from-literal=DISABLE_TRACING=1 \
  --dry-run=client -o yaml | kubectl apply -f -
echo "✅ 로컬 K3s에 AWS 프론트엔드 주소 주입 완료!"

# 🔥 추가됨: 로컬 서비스(cart, currency, loadgenerator, product) 자동 배포
echo "[5/5] 로컬 전용 마이크로서비스 배포 진행 중..."
# kustomization.yaml이 있는 폴더 경로를 지정하여 한 번에 배포합니다.
kubectl apply -k ~/Zero-Trust-IDP/gitops/apps/boutique-local -n boutique-local

echo "✅ 로컬 서비스(Cart, Currency, Product 등) 배포 완료!"


echo "=================================================="
echo "🎉 로컬 환경 세팅이 모두 끝났습니다!"
echo "=================================================="
echo "🚨 [다음 할 일] 🚨"
echo "아래 출력되는 Kubeconfig 내용을 복사해서,"
echo "AWS 마스터 노드에 있는 ArgoCD에 '로컬 클러스터'로 등록해주세요!"
echo "--------------------------------------------------"
sudo cat /etc/rancher/k3s/k3s.yaml
echo "--------------------------------------------------"
