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
    sudo mkdir -p /etc/rancher/k3s
    sudo tee /etc/rancher/k3s/config.yaml > /dev/null <<EOF
    tls-san:
      - "$LOCAL_TS_IP"
      - "127.0.0.1"
    write-kubeconfig-mode: "644"
    EOF

    if ! command -v k3s &> /dev/null; then
        curl -sfL https://get.k3s.io | sh -
    else
        sudo systemctl restart k3s
    fi
    echo "✅ K3s 설치 완료!"

    echo "[3/5] 네임스페이스 및 환경 설정 중..."
    export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
    sleep 10 
    kubectl create namespace boutique-local --dry-run=client -o yaml | kubectl apply -f -

    echo "[4/5] AWS 리소스 정보 주입 (ConfigMap)..."
    # tfvars의 local_tailscale_ip와 AWS 실시간 리소스 정보를 조합
    kubectl create configmap aws-global-env -n boutique-local \
      --from-literal=AWS_REGION="ap-northeast-2" \
      --from-literal=PROJECT_NAME="Zero-Trust-IDP" \
      --from-literal=LOCAL_TAILSCALE_IP="${var.local_tailscale_ip}" \
      --from-literal=AWS_IP="${aws_instance.k3s_server.private_ip}" \
      --from-literal=FRONTEND_ADDR="${aws_lb.aiops_alb.dns_name}:8080" \
      --from-literal=PRODUCT_CATALOG_SERVICE_ADDR="productcatalogservice:3550" \
      --from-literal=DISABLE_PROFILER="1" \
      --from-literal=DISABLE_TRACING="1" \
      --dry-run=client -o yaml | kubectl apply -f -
    echo "✅ 글로벌 환경변수 주입 완료!"

    echo "[5/5] 로컬 전용 마이크로서비스 배포..."
    GITOPS_PATH="/home/ubuntu/Zero-Trust-IDP/gitops/apps/boutique-local"
    if [ -d "$GITOPS_PATH" ]; then
        kubectl apply -k "$GITOPS_PATH" -n boutique-local
        echo "✅ 로컬 마이크로서비스 배포 완료!"
    else
        echo "⚠️  GitOps 경로를 찾을 수 없어 배포를 건너뜁니다: $$GITOPS_PATH"
    fi

    # =====================================================================
    # 🚀 [추가된 자동화 구간] 6/6: ArgoCD CLI 설치 및 로컬 클러스터 자동 등록
    # =====================================================================
    echo "[6/6] 🤖 ArgoCD 로컬 클러스터 자동 등록 (GitOps 자동화)"

    # 1. ArgoCD CLI 설치 (로컬 PC에 없는 경우)
    if ! command -v argocd &> /dev/null; then
        echo "⬇️ ArgoCD CLI 다운로드 중..."
        curl -sSL -o argocd-linux-amd64 https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
        sudo install -m 555 argocd-linux-amd64 /usr/local/bin/argocd
        rm -f argocd-linux-amd64
    fi

    # 2. 로컬 Kubeconfig 파일 생성 (Tailscale IP 적용)
    LOCAL_KUBECONFIG="$HOME/k3s-tailscale.yaml"
    sudo cat /etc/rancher/k3s/k3s.yaml | sed "s/127.0.0.1/$LOCAL_TS_IP/g" > $LOCAL_KUBECONFIG
    sudo chmod 644 $LOCAL_KUBECONFIG

    # 3. 마스터 노드에서 ArgoCD 비밀번호 안전하게 추출 (AWS SSM 활용)
    echo "🔐 마스터 노드에서 ArgoCD 비밀번호를 추출합니다..."
    MASTER_INSTANCE_ID="${aws_instance.k3s_server.id}"
    AWS_REGION="ap-northeast-2"

    ARGOCD_PW=""
    for i in {1..40}; do
        # SSM을 통해 마스터 노드 내부의 ArgoCD 초기 비밀번호 해독 명령어 전송
        CMD_ID=$(aws ssm send-command \
            --region "$AWS_REGION" \
            --instance-ids "$MASTER_INSTANCE_ID" \
            --document-name "AWS-RunShellScript" \
            --parameters commands='["sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml k3s kubectl get secret argocd-initial-admin-secret -n argocd -o jsonpath=\"{.data.password}\" | base64 -d"]' \
            --query 'Command.CommandId' --output text 2>/dev/null || true)
        
        if [ -n "$CMD_ID" ] && [ "$CMD_ID" != "None" ]; then
            sleep 10
            ARGOCD_PW=$(aws ssm get-command-invocation \
                --region "$AWS_REGION" \
                --command-id "$CMD_ID" \
                --instance-id "$MASTER_INSTANCE_ID" \
                --query 'StandardOutputContent' --output text 2>/dev/null || true)
            
            if [ -n "$ARGOCD_PW" ] && [ "$ARGOCD_PW" != "None" ] && [ "$ARGOCD_PW" != "" ]; then
                echo "✅ 비밀번호 추출 완료!"
                break
            fi
        fi
        echo "⏳ ArgoCD 서버가 준비될 때까지 대기 중... ($i/40)"
        sleep 15
    done

    # 4. ArgoCD 자동 로그인 및 클러스터 등록
    ALB_DNS="${aws_lb.aiops_alb.dns_name}"
    
    echo "🌐 ArgoCD 서버에 로그인 중..."
    # 이전에 터미널이 뻗었던 현상을 방지하기 위해 --grpc-web 옵션 적용
    argocd login $ALB_DNS:80 --username admin --password "$ARGOCD_PW" --plaintext --grpc-web

    echo "🔗 로컬 클러스터(boutique-local-cluster)를 연동합니다..."
    argocd cluster add default --name boutique-local-cluster --kubeconfig $LOCAL_KUBECONFIG --yes

    echo "=================================================="
    echo "🎉 로컬 환경 세팅 및 ArgoCD 자동 연동 완벽 종료!"
    echo "=================================================="
    sudo cat /etc/rancher/k3s/k3s.yaml | sed "s/127.0.0.1/$LOCAL_TS_IP/g"
  EOT
}


# [자동화 옵션] 스크립트 파일이 생성되자마자 바로 실행합니다.
resource "null_resource" "auto_run_setup" {
  depends_on = [local_file.local_node_setup_script]

  provisioner "local-exec" {
    command = "sudo ./setup_local_env.sh"
  }
}