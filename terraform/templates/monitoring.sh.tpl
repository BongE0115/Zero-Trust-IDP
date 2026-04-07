#!/bin/bash
set -euxo pipefail

LOG_FILE="/var/log/monitoring-bootstrap.log"
exec > >(tee -a "$LOG_FILE") 2>&1

AWS_REGION="${aws_region}"
MASTER_PRIVATE_IP="${k3s_server_private_ip}"
WORKER_PRIVATE_IP="${k3s_agent_private_ip}"
GITOPS_REPO_URL="${gitops_repo_url}"
GITOPS_TARGET_REVISION="${gitops_target_revision}"
TAILSCALE_AUTH_KEY="${tailscale_auth_key}"

ENABLE_MONITORING_GITHUB_RUNNER="${enable_monitoring_github_runner}"
GITHUB_RUNNER_SCOPE="${github_runner_scope}"
GITHUB_RUNNER_OWNER="${github_runner_owner}"
GITHUB_RUNNER_REPOSITORY="${github_runner_repository}"
GITHUB_RUNNER_LABELS="${github_runner_labels_csv}"
GITHUB_RUNNER_VERSION="${github_runner_version}"
GITHUB_RUNNER_TOKEN_SSM_PARAMETER="${github_runner_token_ssm_parameter}"

# ---------------------------------------------------------
# 1. 기본 패키지 설치
# ---------------------------------------------------------
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  curl unzip gnupg lsb-release apt-transport-https ca-certificates \
  software-properties-common jq awscli

# ---------------------------------------------------------
# 1.5 Tailscale 설치 및 연결
# ---------------------------------------------------------
if ! command -v tailscale >/dev/null 2>&1; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi

systemctl enable tailscaled
systemctl restart tailscaled

if [[ -n "$${TAILSCALE_AUTH_KEY:-}" ]]; then
  tailscale up --authkey "$${TAILSCALE_AUTH_KEY}" --ssh
else
  echo "[WARN] TAILSCALE_AUTH_KEY is empty, skipping tailscale up"
fi

# ---------------------------------------------------------
# 2. kubectl 설치
# ---------------------------------------------------------
if ! command -v kubectl >/dev/null 2>&1; then
  KUBECTL_VERSION="$(curl -fsSL https://dl.k8s.io/release/stable.txt)"
  curl -fsSLo /usr/local/bin/kubectl "https://dl.k8s.io/release/$${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
  chmod +x /usr/local/bin/kubectl
fi

# ---------------------------------------------------------
# 3. Grafana 설치
# ---------------------------------------------------------
mkdir -p /etc/apt/keyrings
curl -fsSL https://apt.grafana.com/gpg.key | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" > /etc/apt/sources.list.d/grafana.list
apt-get update -y
apt-get install -y grafana

mkdir -p /etc/grafana/provisioning/datasources
cat > /etc/grafana/provisioning/datasources/ds-prometheus.yaml <<EOF
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://localhost:9090
    isDefault: true
    access: proxy
    editable: true
EOF

systemctl enable grafana-server
systemctl restart grafana-server

# ---------------------------------------------------------
# 4. Prometheus 설치
# ---------------------------------------------------------
id prometheus >/dev/null 2>&1 || useradd --no-create-home --shell /bin/false prometheus

# 4.1 로컬 Node Exporter 설치
cd /tmp
NODE_EXPORTER_VERSION="1.7.0"
curl -LO "https://github.com/prometheus/node_exporter/releases/download/v$${NODE_EXPORTER_VERSION}/node_exporter-$${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz"
tar xvf "node_exporter-$${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz"
install -m 0755 "node_exporter-$${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter" /usr/local/bin/node_exporter

cat > /etc/systemd/system/node_exporter.service <<'SERVICE'
[Unit]
Description=Node Exporter
After=network.target

[Service]
User=prometheus
ExecStart=/usr/local/bin/node_exporter
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable node_exporter
systemctl start node_exporter

# 4.2 Prometheus 바이너리 설치
PROM_VERSION="2.54.1"
curl -LO "https://github.com/prometheus/prometheus/releases/download/v$${PROM_VERSION}/prometheus-$${PROM_VERSION}.linux-amd64.tar.gz"
tar xvf "prometheus-$${PROM_VERSION}.linux-amd64.tar.gz"

install -m 0755 "prometheus-$${PROM_VERSION}.linux-amd64/prometheus" /usr/local/bin/prometheus
install -m 0755 "prometheus-$${PROM_VERSION}.linux-amd64/promtool" /usr/local/bin/promtool

mkdir -p /etc/prometheus /var/lib/prometheus

# 4.3 Prometheus 설정 파일 작성
cat > /etc/prometheus/prometheus.yml <<EOF
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]

  - job_name: "monitoring-node"
    static_configs:
      - targets: ["localhost:9100"]

  - job_name: "kubernetes-node-exporter"
    tls_config:
      insecure_skip_verify: true
    kubernetes_sd_configs:
      - role: pod
        api_server: "https://$${MASTER_PRIVATE_IP}:6443"
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        action: keep
        regex: node-exporter
      - source_labels: [__meta_kubernetes_pod_host_ip]
        action: replace
        target_label: __address__
        replacement: \$${1}:9100
      - source_labels: [__meta_kubernetes_pod_node_name]
        action: replace
        target_label: node_name

  - job_name: "kubernetes-pods"
    tls_config:
      insecure_skip_verify: true
    kubernetes_sd_configs:
      - role: pod
        api_server: "https://$${MASTER_PRIVATE_IP}:6443"
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
        action: replace
        target_label: __metrics_path__
        regex: (.+)
      - source_labels: [__address__, __meta_kubernetes_pod_annotation_prometheus_io_port]
        action: replace
        target_label: __address__
        regex: ([^:]+)(?::\d+)?;(\d+)
        replacement: \$${1}:\$${2}
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
  --storage.tsdb.path=/var/lib/prometheus \
  --web.enable-lifecycle
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable prometheus
systemctl restart prometheus

# ---------------------------------------------------------
# 5. Bootstrap 자산 저장
# ---------------------------------------------------------
mkdir -p /opt/bootstrap/argocd
mkdir -p /opt/bootstrap/logs

cat <<'EOF' > /opt/bootstrap/argocd/values.yaml
${argocd_values_content}
EOF

ARGOCD_VALUES_B64="$(base64 -w0 /opt/bootstrap/argocd/values.yaml)"

# ---------------------------------------------------------
# 6. SSM 대상 master 인스턴스 찾기
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
# 7. master가 SSM managed node로 등록될 때까지 대기
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
# 8. master에 ArgoCD 설치 + Git clone + root-app apply
# ---------------------------------------------------------
echo "[INFO] Sending bootstrap command to master via SSM..." | tee -a /opt/bootstrap/logs/ssm-bootstrap.log

cat > /tmp/master-bootstrap-commands.json <<EOF
{
  "commands": [
    "#!/bin/bash",
    "set -euxo pipefail",
    "export KUBECONFIG=/etc/rancher/k3s/k3s.yaml",

    "if ! pgrep node_exporter > /dev/null; then curl -LO https://github.com/prometheus/node_exporter/releases/download/v1.7.0/node_exporter-1.7.0.linux-amd64.tar.gz; tar xvf node_exporter-1.7.0.linux-amd64.tar.gz; sudo mv node_exporter-1.7.0.linux-amd64/node_exporter /usr/local/bin/; sudo nohup /usr/local/bin/node_exporter > /dev/null 2>&1 &; fi",

    "sudo /usr/local/bin/k3s kubectl create clusterrolebinding prometheus-view --clusterrole=view --serviceaccount=default:default || true",

    "sudo /usr/local/bin/k3s kubectl create namespace boutique-production || true",
    "sudo /usr/local/bin/k3s kubectl label namespace boutique-production istio-injection=enabled --overwrite || true",

    "if ! command -v helm >/dev/null 2>&1; then curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash; fi",
    "if ! command -v git >/dev/null 2>&1; then sudo apt-get update -y && sudo apt-get install -y git; fi",

    "sudo /usr/local/bin/helm repo add argo https://argoproj.github.io/argo-helm || true",
    "sudo /usr/local/bin/helm repo update",

    "sudo mkdir -p /opt/gitops/bootstrap/argocd",
    "cat > /tmp/argocd-values.b64 <<'\\\\''EOF'\\\\''",
    "$${ARGOCD_VALUES_B64}",
    "EOF",
    "base64 -d /tmp/argocd-values.b64 | sudo tee /opt/gitops/bootstrap/argocd/values.yaml >/dev/null",

    "sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/helm upgrade --install argocd argo/argo-cd --version 8.0.0 -n argocd --create-namespace -f /opt/gitops/bootstrap/argocd/values.yaml",
    "sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/k3s kubectl rollout status deployment/argocd-server -n argocd --timeout=300s",
    "sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/k3s kubectl rollout status deployment/argocd-repo-server -n argocd --timeout=300s",
    "sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/k3s kubectl rollout status statefulset/argocd-application-controller -n argocd --timeout=300s",

    "sudo rm -rf /opt/gitops-repo",
    "git clone -b $${GITOPS_TARGET_REVISION} $${GITOPS_REPO_URL} /opt/gitops-repo",
    "sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/k3s kubectl apply -f /opt/gitops-repo/gitops/bootstrap/root-app.yaml",
    "sudo KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/k3s kubectl get applications -n argocd || true"
  ]
}
EOF

COMMAND_ID="$(aws ssm send-command \
  --region "$AWS_REGION" \
  --instance-ids "$MASTER_INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --comment "Install ArgoCD and apply root-app from Git" \
  --parameters file:///tmp/master-bootstrap-commands.json \
  --query 'Command.CommandId' \
  --output text)"

if [ -z "$${COMMAND_ID:-}" ] || [ "$${COMMAND_ID}" = "None" ]; then
  echo "[ERROR] Failed to send bootstrap command to master." | tee -a /opt/bootstrap/logs/ssm-bootstrap.log
  exit 1
fi

echo "[INFO] Command sent. CommandId=$COMMAND_ID" | tee -a /opt/bootstrap/logs/ssm-bootstrap.log

# ---------------------------------------------------------
# 9. Run Command 완료 대기
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
  echo "[ERROR] Timed out waiting for master bootstrap completion." | tee -a /opt/bootstrap/logs/ssm-bootstrap.log
  exit 1
fi

# ---------------------------------------------------------
# 10. monitoring node용 kubeconfig 생성
# ---------------------------------------------------------
mkdir -p /root/.kube
cat > /root/.kube/config <<EOF
apiVersion: v1
kind: Config
clusters:
- cluster:
    insecure-skip-tls-verify: true
    server: https://$${MASTER_PRIVATE_IP}:6443
  name: aiops-k3s
contexts:
- context:
    cluster: aiops-k3s
    user: aiops-k3s
  name: aiops-k3s
current-context: aiops-k3s
users:
- name: aiops-k3s
  user:
    token: dummy
EOF
chmod 600 /root/.kube/config

# ---------------------------------------------------------
# 11. GitHub self-hosted runner 설치 및 등록
# ---------------------------------------------------------
if [ "$${ENABLE_MONITORING_GITHUB_RUNNER}" = "true" ]; then
  echo "[INFO] Installing GitHub Actions self-hosted runner on monitoring node..." | tee -a /opt/bootstrap/logs/github-runner.log

  RUNNER_ROOT="/opt/actions-runner"
  mkdir -p "$RUNNER_ROOT"
  cd "$RUNNER_ROOT"

  if [ ! -f "$RUNNER_ROOT/actions-runner-linux-x64-$${GITHUB_RUNNER_VERSION}.tar.gz" ]; then
    curl -fsSLo "actions-runner-linux-x64-$${GITHUB_RUNNER_VERSION}.tar.gz" \
      "https://github.com/actions/runner/releases/download/v$${GITHUB_RUNNER_VERSION}/actions-runner-linux-x64-$${GITHUB_RUNNER_VERSION}.tar.gz"
  fi

  if [ ! -f "$RUNNER_ROOT/bin/Runner.Listener" ]; then
    tar xzf "actions-runner-linux-x64-$${GITHUB_RUNNER_VERSION}.tar.gz"
  fi

  INSTANCE_ID="$(curl -fsSL http://169.254.169.254/latest/meta-data/instance-id)"
  PRIVATE_IP="$(curl -fsSL http://169.254.169.254/latest/meta-data/local-ipv4)"
  RUNNER_NAME="monitoring-$${INSTANCE_ID}"

  GITHUB_BOOTSTRAP_TOKEN="$(aws ssm get-parameter \
    --region "$AWS_REGION" \
    --name "$GITHUB_RUNNER_TOKEN_SSM_PARAMETER" \
    --with-decryption \
    --query 'Parameter.Value' \
    --output text)"

  if [ -z "$GITHUB_BOOTSTRAP_TOKEN" ] || [ "$GITHUB_BOOTSTRAP_TOKEN" = "None" ]; then
    echo "[ERROR] Failed to read GitHub runner bootstrap token from SSM." | tee -a /opt/bootstrap/logs/github-runner.log
    exit 1
  fi

  if [ "$GITHUB_RUNNER_SCOPE" = "org" ]; then
    REG_URL="https://api.github.com/orgs/$${GITHUB_RUNNER_OWNER}/actions/runners/registration-token"
    RUNNER_URL="https://github.com/$${GITHUB_RUNNER_OWNER}"
  else
    REG_URL="https://api.github.com/repos/$${GITHUB_RUNNER_OWNER}/$${GITHUB_RUNNER_REPOSITORY}/actions/runners/registration-token"
    RUNNER_URL="https://github.com/$${GITHUB_RUNNER_OWNER}/$${GITHUB_RUNNER_REPOSITORY}"
  fi

  REG_JSON="$(curl -fsSL -X POST \
    -H "Accept: application/vnd.github+json" \
    -H "Authorization: Bearer $${GITHUB_BOOTSTRAP_TOKEN}" \
    "$REG_URL")"

  REG_TOKEN="$(echo "$REG_JSON" | jq -r '.token')"

  if [ -z "$REG_TOKEN" ] || [ "$REG_TOKEN" = "null" ]; then
    echo "[ERROR] Failed to get registration token from GitHub API." | tee -a /opt/bootstrap/logs/github-runner.log
    echo "$REG_JSON" | tee -a /opt/bootstrap/logs/github-runner.log
    exit 1
  fi

  chown -R ubuntu:ubuntu "$RUNNER_ROOT"

  if [ ! -f "$RUNNER_ROOT/.runner" ]; then
    sudo -u ubuntu ./config.sh \
      --unattended \
      --replace \
      --name "$RUNNER_NAME" \
      --url "$RUNNER_URL" \
      --token "$REG_TOKEN" \
      --labels "$GITHUB_RUNNER_LABELS,private-vpc,$PRIVATE_IP" \
      --work "_work"
  else
    echo "[INFO] Runner already configured. Skipping config.sh." | tee -a /opt/bootstrap/logs/github-runner.log
  fi

  ./svc.sh install root || true
  ./svc.sh start || true

  systemctl enable actions.runner.* || true
  systemctl restart actions.runner.* || true
fi

echo "[INFO] Monitoring bootstrap completed successfully." | tee -a "$LOG_FILE"