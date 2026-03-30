# ==================================================
# 로컬 인프라 (On-Premise) 연동 및 자동 실행 설정
# ==================================================

resource "local_file" "local_node_setup_script" {
  filename        = "${path.module}/setup_local_env.sh"
  file_permission = "0755"

  content = <<EOT
#!/bin/bash
set -e

# 1. 실시간 Tailscale IP 추출 (변수 주입 대신 실시간 확인으로 정확도 UP)
LOCAL_TS_IP=$(tailscale ip -4 | head -n 1)

# 2. K3s 설정파일 생성 (가장 중요한 SAN 작업)
sudo mkdir -p /etc/rancher/k3s
sudo tee /etc/rancher/k3s/config.yaml > /dev/null <<EOF
tls-san:
  - "$LOCAL_TS_IP"
  - "127.0.0.1"
write-kubeconfig-mode: "644"
EOF

# 3. K3s 설치 또는 설정 반영을 위한 재시작
if ! command -v k3s &> /dev/null; then
    curl -sfL https://get.k3s.io | sh -
else
    sudo systemctl restart k3s
fi
sleep 10

# 4. 네임스페이스 및 ConfigMap 생성 (형님의 변수화 요청 반영)
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl create namespace boutique-local --dry-run=client -o yaml | kubectl apply -f -

# 하드코딩 없이 테라폼 변수(${var.xxx})를 통해 환경변수 주입
kubectl create configmap aws-global-env -n boutique-local \
  --from-literal=AWS_REGION="${var.aws_region}" \
  --from-literal=PROJECT_NAME="${var.project_name}" \
  --from-literal=LOCAL_TAILSCALE_IP="$LOCAL_TS_IP" \
  --from-literal=AWS_IP="${aws_instance.k3s_server.private_ip}" \
  --from-literal=FRONTEND_ADDR="${aws_lb.aiops_alb.dns_name}:8080" \
  --from-literal=PRODUCT_CATALOG_SERVICE_ADDR="productcatalogservice:3550" \
  --from-literal=DISABLE_PROFILER="1" \
  --dry-run=client -o yaml | kubectl apply -f -

# 5. GitOps 배포 (경로 자동화)
GITOPS_PATH="/home/ubuntu/Zero-Trust-IDP/gitops/apps/boutique-local"
if [ -d "$$GITOPS_PATH" ]; then
    kubectl apply -k "$GITOPS_PATH" -n boutique-local
fi

echo "=================================================="
echo "🚨 아래 Kubeconfig를 긁어서 ArgoCD에 등록하세요 🚨"
# 형님이 올려주신 구조와 똑같이 만들되, IP만 현재 IP로 치환해서 출력
sudo cat /etc/rancher/k3s/k3s.yaml | sed "s/127.0.0.1/$LOCAL_TS_IP/g"
echo "=================================================="
EOT
}

# [자동화 옵션] 스크립트 파일이 생성되자마자 바로 실행합니다.
resource "null_resource" "auto_run_setup" {
  depends_on = [local_file.local_node_setup_script]

  provisioner "local-exec" {
    command = "sudo ./setup_local_env.sh"
  }
}