# ==================================================
# 로컬 인프라 (On-Premise) 연동 및 자동 실행 설정
# ==================================================

resource "local_file" "local_node_setup_script" {
  filename        = "${path.module}/setup_local_env.sh"
  file_permission = "0755"

  # Quoted Heredoc (<<"EOF")을 사용하여 내부의 모든 $ 기호를 테라폼이 무시하도록 설정
  content = <<"EOF"
#!/bin/bash
set -e

# 1. 실시간 Tailscale IP 추출
LOCAL_TS_IP=$(tailscale ip -4 | head -n 1)

# 2. K3s 설정파일 생성 (SAN 작업)
sudo mkdir -p /etc/rancher/k3s
sudo tee /etc/rancher/k3s/config.yaml > /dev/null <<K3S_CONF
tls-san:
  - "$LOCAL_TS_IP"
  - "127.0.0.1"
write-kubeconfig-mode: "644"
K3S_CONF

# 3. K3s 설치 또는 설정 반영을 위한 재시작
if ! command -v k3s &> /dev/null; then
    curl -sfL https://get.k3s.io | sh -
else
    sudo systemctl restart k3s
fi
sleep 10

# 4. 네임스페이스 및 ConfigMap 생성
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl create namespace boutique-local --dry-run=client -o yaml | kubectl apply -f -

# 실행 시 주입된 환경 변수를 사용하여 ConfigMap 생성
kubectl create configmap aws-global-env -n boutique-local \
  --from-literal=AWS_REGION="$TF_VAR_AWS_REGION" \
  --from-literal=PROJECT_NAME="$TF_VAR_PROJECT_NAME" \
  --from-literal=LOCAL_TAILSCALE_IP="$LOCAL_TS_IP" \
  --from-literal=AWS_IP="$TF_VAR_AWS_IP" \
  --from-literal=FRONTEND_ADDR="$TF_VAR_FRONTEND_ADDR:8080" \
  --from-literal=PRODUCT_CATALOG_SERVICE_ADDR="productcatalogservice:3550" \
  --from-literal=DISABLE_PROFILER="1" \
  --dry-run=client -o yaml | kubectl apply -f -

# 5. GitOps 배포
GITOPS_PATH="/home/ubuntu/Zero-Trust-IDP/gitops/apps/boutique-local"
if [ -d "$GITOPS_PATH" ]; then
    kubectl apply -k "$GITOPS_PATH" -n boutique-local
fi

echo "=================================================="
echo "🚨 아래 Kubeconfig를 긁어서 ArgoCD에 등록하세요 🚨"
sudo cat /etc/rancher/k3s/k3s.yaml | sed "s/127.0.0.1/$LOCAL_TS_IP/g"
echo "=================================================="
EOF
}

# 스크립트 실행 시 테라폼 변수를 환경 변수로 주입
resource "null_resource" "auto_run_setup" {
  depends_on = [local_file.local_node_setup_script]

  provisioner "local-exec" {
    command = "sudo ./setup_local_env.sh"

    # 테라폼 변수들을 셸 환경 변수로 매핑
    environment = {
      TF_VAR_AWS_REGION   = var.aws_region
      TF_VAR_PROJECT_NAME = var.project_name
      TF_VAR_AWS_IP       = aws_instance.k3s_server.private_ip
      TF_VAR_FRONTEND_ADDR = aws_lb.aiops_alb.dns_name
    }
  }
}