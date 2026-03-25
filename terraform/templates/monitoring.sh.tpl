#!/bin/bash
set -eux

# 1. 기초 패키지 및 Ansible 설치
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3 python3-pip curl unzip gnupg lsb-release apt-transport-https ca-certificates software-properties-common
apt-get install -y ansible

# ---------------------------------------------------------
# 2. Ansible 환경 구축 (디렉토리 및 SSH 열쇠 설정)
# ---------------------------------------------------------
mkdir -p /home/ubuntu/ansible
chmod 755 /home/ubuntu/ansible

# 2-1. 테라폼으로부터 전달받은 개인키 파일 생성
cat > /home/ubuntu/ansible/id_rsa <<EOF
${ssh_private_key}
EOF
chmod 600 /home/ubuntu/ansible/id_rsa

# 2-2. Ansible 인벤토리 파일 생성
cat > /home/ubuntu/ansible/hosts.ini <<EOF
[k3s_master]
master ansible_host=${k3s_server_private_ip} ansible_user=ubuntu

[k3s_worker]
worker1 ansible_host=${k3s_agent_private_ip} ansible_user=ubuntu

[all:vars]
ansible_python_interpreter=/usr/bin/python3
k3s_token=${k3s_token}
EOF

# 2-3. Ansible 환경 설정
cat > /home/ubuntu/ansible/ansible.cfg <<EOF
[defaults]
inventory = ./hosts.ini
private_key_file = ./id_rsa
host_key_checking = False
EOF

chown -R ubuntu:ubuntu /home/ubuntu/ansible

# ---------------------------------------------------------
# 3. Grafana & Prometheus 설치
# ---------------------------------------------------------
mkdir -p /etc/apt/keyrings
curl -fsSL https://apt.grafana.com/gpg.key | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" > /etc/apt/sources.list.d/grafana.list
apt-get update -y
apt-get install -y grafana
systemctl enable grafana-server
systemctl start grafana-server

useradd --no-create-home --shell /bin/false prometheus || true
cd /tmp
curl -LO https://github.com/prometheus/prometheus/releases/download/v2.54.1/prometheus-2.54.1.linux-amd64.tar.gz
tar xvf prometheus-2.54.1.linux-amd64.tar.gz

cp prometheus-2.54.1.linux-amd64/prometheus /usr/local/bin/
cp prometheus-2.54.1.linux-amd64/promtool /usr/local/bin/

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
        - "${k3s_server_private_ip}:10250"
        - "${k3s_agent_private_ip}:10250"
        - "${k3s_server_private_ip}:9100"
        - "${k3s_agent_private_ip}:9100"
EOF

chown -R prometheus:prometheus /etc/prometheus
chown -R prometheus:prometheus /var/lib/prometheus

cat > /etc/systemd/system/prometheus.service <<SERVICE
[Unit]
Description=Prometheus
After=network.target

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/usr/local/bin/prometheus --config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/var/lib/prometheus
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable prometheus
systemctl start prometheus

# ---------------------------------------------------------
# 4. 자동 설치를 위한 Ansible 실행
# ---------------------------------------------------------

# 4-1. 설치용 파일 생성
# 디렉토리 구조 생성 
mkdir -p /home/ubuntu/ansible/gitops/bootstrap/argocd

cat <<'EOF' > /home/ubuntu/ansible/setup_k3s.yml
${ansible_playbook_content}
EOF

cat <<'EOF' > /home/ubuntu/ansible/root-app.yaml
${argocd_root_app_content}
EOF

cat <<'EOF' > /home/ubuntu/ansible/gitops/bootstrap/argocd/values.yaml
${argocd_values_content}
EOF

chown -R ubuntu:ubuntu /home/ubuntu/ansible

# 4-2. Ansible 실행
cd /home/ubuntu/ansible
sudo -u ubuntu touch install.log

# 1단계: setup_k3s 실행
sudo -u ubuntu ansible-playbook -i hosts.ini setup_k3s.yml >> install.log 2>&1

# 2단계: ArgoCD 기본 readiness 확인
sudo -u ubuntu ssh -i /home/ubuntu/ansible/id_rsa -o StrictHostKeyChecking=no ubuntu@${k3s_server_private_ip} \
  "sudo k3s kubectl rollout status deployment argocd-server -n argocd --timeout=300s" >> install.log 2>&1

# 3단계: root app 전달
sudo -u ubuntu scp -i /home/ubuntu/ansible/id_rsa -o StrictHostKeyChecking=no \
  /home/ubuntu/ansible/root-app.yaml \
  ubuntu@${k3s_server_private_ip}:/tmp/root-app.yaml

# 4단계: root app 등록
sudo -u ubuntu ssh -i /home/ubuntu/ansible/id_rsa -o StrictHostKeyChecking=no ubuntu@${k3s_server_private_ip} \
  "sudo k3s kubectl apply -f /tmp/root-app.yaml" >> install.log 2>&1

# 5단계: ArgoCD 초기 비밀번호 생성 대기
echo "Waiting for ArgoCD initial secret to be generated..." >> install.log
for i in {1..20}; do
  if sudo -u ubuntu ssh -i /home/ubuntu/ansible/id_rsa -o StrictHostKeyChecking=no ubuntu@${k3s_server_private_ip} \
    "sudo k3s kubectl get secret -n argocd argocd-initial-admin-secret" > /dev/null 2>&1; then
    echo "ArgoCD secret found." >> install.log
    break
  fi
  echo "Still waiting for ArgoCD secret... ($i/20)" >> install.log
  sleep 15
done