#!/bin/bash
set -euxo pipefail

LOG_FILE="/var/log/monitoring-bootstrap.log"
exec > >(tee -a "$LOG_FILE") 2>&1

AWS_REGION="${aws_region}"
MASTER_PRIVATE_IP="${k3s_server_private_ip}"
WORKER_PRIVATE_IP="${k3s_agent_private_ip}"
GITOPS_REPO_URL="${gitops_repo_url}"
GITOPS_TARGET_REVISION="${gitops_target_revision}"

# ---------------------------------------------------------
# 1. 기본 패키지 설치
# ---------------------------------------------------------
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  curl unzip gnupg lsb-release apt-transport-https ca-certificates \
  software-properties-common jq awscli

# ---------------------------------------------------------
# 2. Grafana 설치
# ---------------------------------------------------------
mkdir -p /etc/apt/keyrings
curl -fsSL https://apt.grafana.com/gpg.key | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" > /etc/apt/sources.list.d/grafana.list
apt-get update -y
apt-get install -y grafana
systemctl enable grafana-server
systemctl restart grafana-server

# ---------------------------------------------------------
# 3. Prometheus 설치
# ---------------------------------------------------------
id prometheus >/dev/null 2>&1 || useradd --no-create-home --shell /bin/false prometheus

cd /tmp
PROM_VERSION="2.54.1"
curl -LO "https://github.com/prometheus/prometheus/releases/download/v$${PROM_VERSION}/prometheus-$${PROM_VERSION}.linux-amd64.tar.gz"
tar xvf "prometheus-$${PROM_VERSION}.linux-amd64.tar.gz"

install -m 0755 "prometheus-$${PROM_VERSION}.linux-amd64/prometheus" /usr/local/bin/prometheus
install -m 0755 "prometheus-$${PROM_VERSION}.linux-amd64/promtool" /usr/local/bin/promtool

mkdir -p /etc/prometheus /var/lib/prometheus

cat > /etc/prometheus/prometheus.yml <<EOF
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]

  - job_name: "k3s-nodes"
    metrics_path: "/metrics"
    static_configs:
      - targets:
        - "$${MASTER_PRIVATE_IP}:10250"
        - "$${WORKER_PRIVATE_IP}:10250"
        - "$${MASTER_PRIVATE_IP}:9100"
        - "$${WORKER_PRIVATE_IP}:9100"
EOF

chown -R prometheus:prometheus /etc/prometheus
chown -R prometheus:prometheus /var/lib/prometheus

cat > /etc/systemd/system/prometheus.service <<'SERVICE'
[Unit]
Description=Prometheus
After=network.target

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/usr/local/bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/var/lib/prometheus
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable prometheus
systemctl restart prometheus

# ---------------------------------------------------------
# 4. Bootstrap 자산 저장
# ---------------------------------------------------------
mkdir -p /opt/bootstrap/argocd
mkdir -p /opt/bootstrap/logs

cat <<'EOF' > /opt/bootstrap/argocd/values.yaml
${argocd_values_content}
EOF

ARGOCD_VALUES_B64="$(base64 -w0 /opt/bootstrap/argocd/values.yaml)"

# ---------------------------------------------------------
# 5. SSM 대상 master 인스턴스 찾기
#    전제: master 태그 Role=K3s_Server
# ---------------------------------------------------------
echo "[INFO] Discovering K3s master instance by tag..." | tee -a /opt/bootstrap/logs/ssm-bootstrap.log

MASTER_INSTANCE_ID=""
for i in {1..40}; do
  MASTER_INSTANCE_ID="$(aws ec2 describe-instances \
    --region "$AWS_REGION" \
    --filters "Name=tag:Role,Values=K3s_Server" "Name=instance-state-name,Values=running" \
    --query 'Reservations[0].Instances[0].InstanceId' \
    --output text || true)"

  if [ -n "$MASTER_INSTANCE_ID" ] && [ "$MASTER_INSTANCE_ID" != "None" ]; then
    echo "[INFO] Master instance found: $MASTER_INSTANCE_ID" | tee -a /opt/bootstrap/logs/ssm-bootstrap.log
    break
  fi

  echo "[INFO] Waiting for master instance discovery... ($i/40)" | tee -a /opt/bootstrap/logs/ssm-bootstrap.log
  sleep 15
done

if [ -z "$MASTER_INSTANCE_ID" ] || [ "$MASTER_INSTANCE_ID" = "None" ]; then
  echo "[ERROR] Failed to discover K3s master instance." | tee -a /opt/bootstrap/logs/ssm-bootstrap.log
  exit 1
fi

# ---------------------------------------------------------
# 6. master가 SSM managed node로 등록될 때까지 대기
# ---------------------------------------------------------
echo "[INFO] Waiting for master to appear in SSM..." | tee -a /opt/bootstrap/logs/ssm-bootstrap.log

ONLINE_PING=""
for i in {1..40}; do
  ONLINE_PING="$(aws ssm describe-instance-information \
    --region "$AWS_REGION" \
    --filters "Key=InstanceIds,Values=$MASTER_INSTANCE_ID" \
    --query 'InstanceInformationList[0].PingStatus' \
    --output text || true)"

  if [ "$ONLINE_PING" = "Online" ]; then
    echo "[INFO] Master is online in SSM." | tee -a /opt/bootstrap/logs/ssm-bootstrap.log
    break
  fi

  echo "[INFO] Waiting for SSM registration... ($i/40)" | tee -a /opt/bootstrap/logs/ssm-bootstrap.log
  sleep 15
done

if [ "$${ONLINE_PING:-}" != "Online" ]; then
  echo "[ERROR] Master did not become online in SSM." | tee -a /opt/bootstrap/logs/ssm-bootstrap.log
  exit 1
fi

# ---------------------------------------------------------
# 7. master에 ArgoCD 설치 + Git clone + root-app apply
# ---------------------------------------------------------
echo "[INFO] Sending bootstrap command to master via SSM..." | tee -a /opt/bootstrap/logs/ssm-bootstrap.log

COMMAND_ID="$(aws ssm send-command \
  --region "$AWS_REGION" \
  --instance-ids "$MASTER_INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --comment "Install ArgoCD and apply root-app from Git" \
  --parameters commands='[
    "#!/bin/bash",
    "set -euxo pipefail",
    "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml",
    "if ! command -v helm >/dev/null 2>&1; then curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash; fi",
    "if ! command -v git >/dev/null 2>&1; then sudo apt-get update -y && sudo apt-get install -y git; fi",
    "sudo /usr/local/bin/helm repo add argo https://argoproj.github.io/argo-helm || true",
    "sudo /usr/local/bin/helm repo update",
    "sudo mkdir -p /opt/gitops/bootstrap/argocd",
    "cat > /tmp/argocd-values.b64 <<'\''EOF'\''",
    "'"$ARGOCD_VALUES_B64"'",
    "EOF",
    "base64 -d /tmp/argocd-values.b64 | sudo tee /opt/gitops/bootstrap/argocd/values.yaml >/dev/null",
    "sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml helm upgrade --install argocd argo/argo-cd --version 8.0.0 -n argocd --create-namespace -f /opt/gitops/bootstrap/argocd/values.yaml",
    "sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml k3s kubectl rollout status deployment/argocd-server -n argocd --timeout=300s",
    "sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml k3s kubectl rollout status deployment/argocd-repo-server -n argocd --timeout=300s",
    "sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml k3s kubectl rollout status statefulset/argocd-application-controller -n argocd --timeout=300s",
    "sudo rm -rf /opt/gitops-repo",
    "git clone -b '"$GITOPS_TARGET_REVISION"' '"$GITOPS_REPO_URL"' /opt/gitops-repo",
    "sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml k3s kubectl apply -f /opt/gitops-repo/gitops/bootstrap/root-app.yaml",
    "sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml k3s kubectl get applications -n argocd || true"
  ]' \
  --query 'Command.CommandId' \
  --output text)"

echo "[INFO] Command sent. CommandId=$COMMAND_ID" | tee -a /opt/bootstrap/logs/ssm-bootstrap.log
# ---------------------------------------------------------
# 8. Run Command 완료 대기
# ---------------------------------------------------------
FINAL_STATUS=""
for i in {1..40}; do
  FINAL_STATUS="$(aws ssm get-command-invocation \
    --region "$AWS_REGION" \
    --command-id "$COMMAND_ID" \
    --instance-id "$MASTER_INSTANCE_ID" \
    --query 'Status' \
    --output text || true)"

  case "$FINAL_STATUS" in
    Success)
      echo "[INFO] ArgoCD install and root-app apply completed successfully." | tee -a /opt/bootstrap/logs/ssm-bootstrap.log
      break
      ;;
    Pending|InProgress|Delayed|"")
      echo "[INFO] Waiting for command completion... status=$FINAL_STATUS ($i/40)" | tee -a /opt/bootstrap/logs/ssm-bootstrap.log
      sleep 15
      ;;
    *)
      echo "[ERROR] Command failed with status=$FINAL_STATUS" | tee -a /opt/bootstrap/logs/ssm-bootstrap.log
      aws ssm get-command-invocation \
        --region "$AWS_REGION" \
        --command-id "$COMMAND_ID" \
        --instance-id "$MASTER_INSTANCE_ID" \
        --output json | tee -a /opt/bootstrap/logs/ssm-bootstrap.log || true
      exit 1
      ;;
  esac
done

if [ "$${FINAL_STATUS:-}" != "Success" ]; then
  echo "[ERROR] ArgoCD install/root-app apply did not complete successfully." | tee -a /opt/bootstrap/logs/ssm-bootstrap.log
  exit 1
fi

# ---------------------------------------------------------
# 9. ArgoCD 초기 비밀번호 조회
# ---------------------------------------------------------
echo "[INFO] Fetching ArgoCD initial admin password..." | tee -a /opt/bootstrap/logs/ssm-bootstrap.log

PASSWORD_COMMAND_ID="$(aws ssm send-command \
  --region "$AWS_REGION" \
  --instance-ids "$MASTER_INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --comment "Get ArgoCD initial admin password" \
  --parameters commands='[
    "#!/bin/bash",
    "set -euxo pipefail",
    "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml",
    "for i in {1..20}; do",
    "  if sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml k3s kubectl get secret -n argocd argocd-initial-admin-secret >/dev/null 2>&1; then break; fi",
    "  sleep 15",
    "done",
    "sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml k3s kubectl get secret argocd-initial-admin-secret -n argocd -o jsonpath='\''{.data.password}'\'' | base64 -d"
  ]' \
  --query 'Command.CommandId' \
  --output text)"

PASSWORD_STATUS=""
for i in {1..20}; do
  PASSWORD_STATUS="$(aws ssm get-command-invocation \
    --region "$AWS_REGION" \
    --command-id "$PASSWORD_COMMAND_ID" \
    --instance-id "$MASTER_INSTANCE_ID" \
    --query 'Status' \
    --output text || true)"

  case "$PASSWORD_STATUS" in
    Success)
      break
      ;;
    Pending|InProgress|Delayed|"")
      echo "[INFO] Waiting for password command completion... status=$PASSWORD_STATUS ($i/20)" | tee -a /opt/bootstrap/logs/ssm-bootstrap.log
      sleep 10
      ;;
    *)
      echo "[ERROR] Password fetch failed with status=$PASSWORD_STATUS" | tee -a /opt/bootstrap/logs/ssm-bootstrap.log
      aws ssm get-command-invocation \
        --region "$AWS_REGION" \
        --command-id "$PASSWORD_COMMAND_ID" \
        --instance-id "$MASTER_INSTANCE_ID" \
        --output json | tee -a /opt/bootstrap/logs/ssm-bootstrap.log || true
      exit 1
      ;;
  esac
done

if [ "$${PASSWORD_STATUS:-}" != "Success" ]; then
  echo "[ERROR] Password fetch did not complete successfully." | tee -a /opt/bootstrap/logs/ssm-bootstrap.log
  exit 1
fi

aws ssm get-command-invocation \
  --region "$AWS_REGION" \
  --command-id "$PASSWORD_COMMAND_ID" \
  --instance-id "$MASTER_INSTANCE_ID" \
  --query 'StandardOutputContent' \
  --output text | tee /opt/bootstrap/logs/argocd-initial-password.txt

echo "[INFO] Monitoring bootstrap completed." | tee -a /opt/bootstrap/logs/ssm-bootstrap.log