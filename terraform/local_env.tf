# ==================================================
# 로컬 인프라 (On-Premise) 연동 및 자동 실행 설정
# ==================================================

resource "local_file" "local_node_setup_script" {
  filename        = "${path.module}/setup_local_env.sh"
  file_permission = "0755"

  content = <<-EOT
    #!/bin/bash
    set -e

    echo "=================================================="
    echo "🚀 AIOps 로컬 환경(On-Premise) 자동 구축 시작"
    echo "=================================================="

    echo "[1/5] Tailscale 설치 및 VPN 연결 중..."
    if ! command -v tailscale &> /dev/null; then
        curl -fsSL https://tailscale.com/install.sh | sh
    fi
    # 테라폼 변수(tfvars) 주입
    sudo tailscale up --authkey=${var.tailscale_auth_key} --hostname=aiops-local-worker --accept-routes

    # 스크립트 실행 시점의 실제 Tailscale IP 추출 (Kubeconfig 출력용)
    LOCAL_TS_IP=$(tailscale ip -4 | head -n 1)
    echo "✅ Tailscale 연동 완료! (현재 IP: $LOCAL_TS_IP)"

    echo "[2/5] K3s 클러스터 설치 중..."
    if ! command -v k3s &> /dev/null; then
        curl -sfL https://get.k3s.io | sh -
    fi
    echo "✅ K3s 설치 완료!"

    echo "[3/5] 네임스페이스 및 환경 설정 중..."
    sudo chmod 644 /etc/rancher/k3s/k3s.yaml
    export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
    sleep 5
    kubectl create namespace boutique-local --dry-run=client -o yaml | kubectl apply -f -

    echo "[4/5] AWS 리소스 정보 주입 (ConfigMap)..."
    # tfvars의 local_tailscale_ip와 AWS 실시간 리소스 정보를 조합
    kubectl create configmap aws-global-env -n boutique-local \
      --from-literal=AWS_REGION="ap-northeast-2" \
      --from-literal=PROJECT_NAME="Zero-Trust-IDP" \
      --from-literal=LOCAL_TAILSCALE_IP="${var.local_tailscale_ip}" \
      --from-literal=AWS_IP="${aws_instance.k3s_server.private_ip}" \
      --from-literal=FRONTEND_ADDR="${aws_lb.aiops_alb.dns_name}:30081" \
      --from-literal=PRODUCT_CATALOG_SERVICE_ADDR="productcatalogservice:3550" \
      --from-literal=DISABLE_PROFILER="1" \
      --from-literal=DISABLE_TRACING="1" \
      --dry-run=client -o yaml | kubectl apply -f -
    echo "✅ 글로벌 환경변수 주입 완료!"

    echo "[5/5] 로컬 전용 마이크로서비스 배포..."
    GITOPS_PATH="$HOME/Zero-Trust-IDP/gitops/apps/boutique-local"
    if [ -d "$GITOPS_PATH" ]; then
        kubectl apply -k "$GITOPS_PATH" -n boutique-local
        echo "✅ 로컬 마이크로서비스 배포 완료!"
    else
        echo "⚠️  GitOps 경로를 찾을 수 없어 배포를 건너뜁니다: $GITOPS_PATH"
    fi

    echo "=================================================="
    echo "🎉 로컬 환경 세팅 완료!"
    echo "=================================================="
    echo "🚨 [ArgoCD 등록용 Kubeconfig] 🚨"
    echo "--------------------------------------------------"
    # 127.0.0.1을 실제 접속 가능한 Tailscale IP로 치환하여 출력
    sudo cat /etc/rancher/k3s/k3s.yaml | sed "s/127.0.0.1/$LOCAL_TS_IP/g"
    echo "--------------------------------------------------"
  EOT
}

# [자동화 옵션] 스크립트 파일이 생성되자마자 바로 실행합니다.
resource "null_resource" "auto_run_setup" {
  depends_on = [local_file.local_node_setup_script]

  provisioner "local-exec" {
    command = "./setup_local_env.sh"
  }
}