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

    echo "[1/7] Tailscale 설치 및 VPN 연결 중..."
    if ! command -v tailscale &> /dev/null; then
        curl -fsSL https://tailscale.com/install.sh | sh
    fi
    sudo tailscale up --authkey=${var.tailscale_auth_key} --hostname=aiops-local-worker --accept-routes

    LOCAL_TS_IP=$(tailscale ip -4 | head -n 1)
    echo "✅ Tailscale 연동 완료! (현재 IP: $LOCAL_TS_IP)"

    echo "[2/7] K3s 클러스터 설치 중..."
    sudo mkdir -p /etc/rancher/k3s
    
    cat <<EOF | sudo tee /etc/rancher/k3s/config.yaml > /dev/null
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

    echo "⏳ K3s API 서버 시작 및 Kubeconfig 파일 생성 대기 중..."
    for i in {1..30}; do
        if [ -f /etc/rancher/k3s/k3s.yaml ]; then
            echo "✅ Kubeconfig 파일 생성 확인!"
            break
        fi
        sleep 2
    done
    sleep 5

    # 🔍 [검증 1] 로컬 K3s 노드 확인
    echo "🔍 [검증] 로컬 K3s 노드 상태:"
    sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl get nodes

    echo "[3/7] 네임스페이스 및 환경 설정 중..."
    sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl create namespace boutique-local --dry-run=client -o yaml | sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl apply -f -

    echo "[4/7] AWS 리소스 정보 주입 (ConfigMap)..."
    sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl create configmap aws-global-env -n boutique-local \
      --from-literal=AWS_REGION="ap-northeast-2" \
      --from-literal=PROJECT_NAME="Zero-Trust-IDP" \
      --from-literal=LOCAL_TAILSCALE_IP="$LOCAL_TS_IP" \
      --from-literal=AWS_IP="${aws_instance.k3s_server.private_ip}" \
      --from-literal=FRONTEND_ADDR="${aws_lb.aiops_alb.dns_name}:8080" \
      --from-literal=PRODUCT_CATALOG_SERVICE_ADDR="productcatalogservice:3550" \
      --from-literal=DISABLE_PROFILER="1" \
      --from-literal=DISABLE_TRACING="1" \
      --dry-run=client -o yaml | sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl apply -f -
    
    sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl create configmap aws-global-env -n default \
      --from-literal=LOCAL_TAILSCALE_IP="$LOCAL_TS_IP" \
      --dry-run=client -o yaml | sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl apply -f -
      
    # 🔍 [검증 2] 로컬 ConfigMap 확인
    echo "🔍 [검증] 로컬 ConfigMap 생성 결과:"
    sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl get configmap aws-global-env -n boutique-local

    echo "[5/7] 로컬 전용 마이크로서비스 배포..."
    GITOPS_PATH="/home/ubuntu/Zero-Trust-IDP/gitops/apps/boutique-local"
    if [ -d "$GITOPS_PATH" ]; then
        sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl apply -k "$GITOPS_PATH" -n boutique-local
        echo "✅ 로컬 마이크로서비스 배포 완료!"
    else
        echo "⚠️ GitOps 경로를 찾을 수 없어 배포를 건너뜁니다: $GITOPS_PATH"
    fi

    # 🔍 [검증 3] 로컬 파드 배포 상태 확인
    echo "🔍 [검증] 로컬 클러스터 파드 목록:"
    sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl get pods -n boutique-local

    echo "[6/7] 🤖 AWS SSM을 통해 마스터 노드의 ArgoCD 자동 연동을 시작합니다..."
    LOCAL_KUBECONFIG_B64=$(sudo cat /etc/rancher/k3s/k3s.yaml | sed "s/127.0.0.1/$LOCAL_TS_IP/g" | base64 -w 0)
    MASTER_INSTANCE_ID="${aws_instance.k3s_server.id}"
    AWS_REGION="ap-northeast-2"

    aws ssm send-command \
      --region "$AWS_REGION" \
      --instance-ids "$MASTER_INSTANCE_ID" \
      --document-name "AWS-RunShellScript" \
      --no-cli-pager \
      --parameters commands='[
        "#!/bin/bash",
        "set -e",
        "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml",
        
        "kubectl create configmap aws-global-env -n boutique-local --from-literal=AWS_REGION=\"ap-northeast-2\" --from-literal=PROJECT_NAME=\"Zero-Trust-IDP\" --from-literal=LOCAL_TAILSCALE_IP=\"'$LOCAL_TS_IP'\" --from-literal=AWS_IP=\"'${aws_instance.k3s_server.private_ip}'\" --from-literal=FRONTEND_ADDR=\"'${aws_lb.aiops_alb.dns_name}:8080'\" --from-literal=PRODUCT_CATALOG_SERVICE_ADDR=\"productcatalogservice:3550\" --from-literal=DISABLE_PROFILER=\"1\" --from-literal=DISABLE_TRACING=\"1\" --dry-run=client -o yaml | kubectl apply -f -",

        "echo \"🔍 [검증] 마스터 노드 ConfigMap 확인:\"",
        "kubectl get configmap aws-global-env -n boutique-local || true",

        "MASTER_TS_IP=\$(tailscale ip -4 | head -n 1)",
        "sudo sed -i \"s/127.0.0.1/\$MASTER_TS_IP/g\" /etc/rancher/k3s/k3s.yaml",
        "while ! kubectl get pods -n argocd | grep argocd-server | grep Running; do sleep 5; done",
        
        "echo '"$LOCAL_KUBECONFIG_B64"' | base64 -d > /tmp/local-cluster.yaml",
        
        "KUBECONFIG=/tmp/local-cluster.yaml kubectl config rename-context default local-pc || true",
        "KUBECONFIG=/tmp/local-cluster.yaml kubectl config set-cluster default --insecure-skip-tls-verify=true",
        "sed -i \"/certificate-authority-data/d\" /tmp/local-cluster.yaml",

        "ARGOCD_PW=\$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath=\"{.data.password}\" | base64 -d)",
        "until argocd login localhost:30080 --username admin --password \$ARGOCD_PW --plaintext; do sleep 5; done",
        
        "argocd cluster add local-pc --name boutique-local-cluster --kubeconfig /tmp/local-cluster.yaml --yes || true",
        
        "echo \"🔍 [검증] ArgoCD 클러스터 연결 목록 확인:\"",
        "argocd cluster list",

        "kubectl patch application boutique-local -n argocd --type=\"json\" -p=\"[{\\\"op\\\": \\\"replace\\\", \\\"path\\\": \\\"/spec/destination\\\", \\\"value\\\": {\\\"name\\\": \\\"boutique-local-cluster\\\", \\\"namespace\\\": \\\"boutique-local\\\"}}]\"",
        
        "argocd app set boutique-local --sync-policy automated --self-heal --sync-option CreateNamespace=true",
        "argocd app sync boutique-local || true",
        
        "kubectl delete pods --all -n boutique-local || true",
        "echo \"🎉 ArgoCD 연동 및 패치 완료!\""
      ]'

    echo "[7/7] 🤖 워커 노드(Worker Node) K3s 클러스터 자동 조인 시작..."
    
    COMMAND_ID=$(aws ssm send-command \
      --region "$AWS_REGION" \
      --instance-ids "$MASTER_INSTANCE_ID" \
      --document-name "AWS-RunShellScript" \
      --parameters commands="cat /var/lib/rancher/k3s/server/node-token" \
      --query "Command.CommandId" \
      --output text)
    
    sleep 30
    
    NODE_TOKEN=$(aws ssm get-command-invocation \
      --region "$AWS_REGION" \
      --command-id "$COMMAND_ID" \
      --instance-id "$MASTER_INSTANCE_ID" \
      --query "StandardOutputContent" \
      --output text | tr -d '\n')

    echo "✅ 마스터 토큰 확보 완료: $${NODE_TOKEN:0:15}..."

    WORKER_INSTANCE_ID="${aws_instance.k3s_worker.id}" 
    MASTER_PRIVATE_IP="${aws_instance.k3s_server.private_ip}"

    # 워커 노드에 조인 명령 쏘기
    aws ssm send-command \
      --region "$AWS_REGION" \
      --instance-ids "$WORKER_INSTANCE_ID" \
      --document-name "AWS-RunShellScript" \
      --no-cli-pager \
      --parameters commands='[
        "#!/bin/bash",
        "set -e",
        "echo \"[Worker] K3s 워커 노드 설치 및 마스터 조인을 시작합니다...\"",
        "curl -sfL https://get.k3s.io | K3S_URL=https://'"$MASTER_PRIVATE_IP"':6443 K3S_TOKEN=\"'"$NODE_TOKEN"'\" sh -",
        "echo \"🎉 워커 노드 클러스터 조인 완벽 성공!\""
      ]'

    echo "⏳ 워커 노드가 마스터에 붙을 때까지 대기 중..."
    sleep 30

    # 🔍 [검증 4] 마스터 노드에서 전체 노드(워커 포함) 상태 확인
    echo "🔍 [검증] 최종 하이브리드 클러스터 노드 상태 (마스터에서 조회):"
    aws ssm send-command \
      --region "$AWS_REGION" \
      --instance-ids "$MASTER_INSTANCE_ID" \
      --document-name "AWS-RunShellScript" \
      --no-cli-pager \
      --parameters commands='[
        "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml",
        "kubectl get nodes"
      ]'

    echo "=================================================="
    echo "🎉 로컬 + 마스터 + 워커 하이브리드 인프라 풀 오토 세팅 진짜 끝!"
    echo "=================================================="
  EOT
}

resource "null_resource" "auto_run_setup" {
  triggers = {
    script_hash = md5(local_file.local_node_setup_script.content)
  }

  provisioner "local-exec" {
    command = "bash ./setup_local_env.sh" 
  }
}