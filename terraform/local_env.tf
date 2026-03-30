# ==================================================
# --------------------------------------------------
#        로컬 인프라 (On-Premise) 연동 자동화
# --------------------------------------------------
# ==================================================
# 테라폼은 로컬 물리 장비를 직접 제어할 수 없으므로,
# 로컬 장비에서 1초 만에 실행할 수 있는 '자동 세팅 스크립트'를 로컬 PC(.tf 파일이 있는 곳)에 생성해 줍니다.

resource "local_file" "local_node_setup_script" {
  filename        = "${path.module}/setup_local_env.sh"
  file_permission = "0755" # 실행 가능한 권한 부여

  content = <<-EOT
    #!/bin/bash
    set -e

    echo "=================================================="
    echo "🚀 AIOps 로컬 환경(On-Premise) 자동 구축 스크립트"
    echo "=================================================="

    echo "[1/4] Tailscale 설치 및 AWS 망(VPN) 조인 진행 중..."
    curl -fsSL https://tailscale.com/install.sh | sh
    # 테라폼 변수로 입력받은 Tailscale Auth Key를 그대로 주입합니다.
    sudo tailscale up --authkey=${var.tailscale_auth_key} --hostname=aiops-local-worker
    echo "✅ Tailscale 연동 완료! (로컬 ↔ AWS 터널링 성공)"

    echo "[2/4] 가벼운 로컬 K3s 클러스터 설치 진행 중..."
    # 로컬은 마스터/워커 구분 없이 단일 클러스터로 가볍게 띄웁니다.
    curl -sfL https://get.k3s.io | sh -
    echo "✅ 로컬 K3s 설치 완료!"

    echo "[3/4] Kubeconfig 권한 설정 및 네임스페이스 생성..."
    sudo chmod 644 /etc/rancher/k3s/k3s.yaml
    export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
    
    # K3s가 완전히 뜰 때까지 잠시 대기
    sleep 10 
    
    kubectl create namespace boutique-local --dry-run=client -o yaml | kubectl apply -f -
    echo "✅ boutique-local 네임스페이스 생성 완료!"

    # 🔥 추가된 마법: 테라폼이 생성한 ALB 주소를 로컬 K3s ConfigMap으로 주입
    echo "[4/4] AWS ALB 주소를 로컬 환경변수(ConfigMap)로 주입합니다..."
    kubectl create configmap global-env \
      --namespace boutique-local \
      --from-literal=FRONTEND_ADDR="${aws_lb.aiops_alb.dns_name}:80" \
      --from-literal=AWS_MASTER_IP="${aws_instance.k3s_server.private_ip}" \  # 🔥 이거 추가!
      --dry-run=client -o yaml | kubectl apply -f -
    echo "✅ 로컬 K3s에 AWS 프론트엔드 주소 주입 완료!"

    echo "=================================================="
    echo "🎉 로컬 환경 세팅이 모두 끝났습니다!"
    echo "=================================================="
    echo "🚨 [다음 할 일] 🚨"
    echo "아래 출력되는 Kubeconfig 내용을 복사해서,"
    echo "AWS 마스터 노드에 있는 ArgoCD에 '로컬 클러스터'로 등록해주세요!"
    echo "--------------------------------------------------"
    sudo cat /etc/rancher/k3s/k3s.yaml
    echo "--------------------------------------------------"
  EOT
}