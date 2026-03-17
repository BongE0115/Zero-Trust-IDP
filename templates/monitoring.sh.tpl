#!/bin/bash
set -eux

# 1. 기초 패키지 및 Ansible 설치 (기존 유지)
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3 python3-pip curl unzip gnupg lsb-release apt-transport-https ca-certificates software-properties-common
apt-get install -y ansible [cite: 46]

# ---------------------------------------------------------
# 💡 추가: Ansible 인벤토리 파일 생성
# 엔서블이 마스터와 워커 노드의 IP를 알 수 있도록 파일을 미리 만들어둡니다.
# ---------------------------------------------------------
mkdir -p /home/ubuntu/ansible
cat > /home/ubuntu/ansible/hosts.ini <<EOF
[k3s_master]
master ansible_host=${k3s_server_private_ip} ansible_user=ubuntu

[k3s_worker]
worker1 ansible_host=${k3s_agent_private_ip} ansible_user=ubuntu

[all:vars]
ansible_python_interpreter=/usr/bin/python3
k3s_token=${k3s_token}
EOF
chown -R ubuntu:ubuntu /home/ubuntu/ansible

# 2. Grafana 설치 및 실행 (기존 유지) [cite: 46, 47]
mkdir -p /etc/apt/keyrings
curl -fsSL https://apt.grafana.com/gpg.key | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" > /etc/apt/sources.list.d/grafana.list
apt-get update -y
apt-get install -y grafana
systemctl enable grafana-server
systemctl start grafana-server

# 3. Prometheus 설치 (기존 유지) [cite: 48]
useradd --no-create-home --shell /bin/false prometheus || true
cd /tmp
curl -LO https://github.com/prometheus/prometheus/releases/download/v2.54.1/prometheus-2.54.1.linux-amd64.tar.gz
tar xvf prometheus-2.54.1.linux-amd64.tar.gz

mkdir -p /etc/prometheus /var/lib/prometheus
cp prometheus-2.54.1.linux-amd64/prometheus /usr/local/bin/
cp prometheus-2.54.1.linux-amd64/promtool /usr/local/bin/
cp -r prometheus-2.54.1.linux-amd64/consoles /etc/prometheus
cp -r prometheus-2.54.1.linux-amd64/console_libraries /etc/prometheus

# 4. Prometheus 설정 (수정됨)
cat > /etc/prometheus/prometheus.yml <<PROM
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]

  - job_name: "k3s-nodes"
    metrics_path: '/metrics'  # 💡 K3s 노드의 메트릭 경로 명시
    scheme: 'http'            # 💡 우선은 HTTP로 설정 (설치 직후 확인용)
    static_configs:
      - targets:
          - "${k3s_server_private_ip}:10250"
          - "${k3s_agent_private_ip}:10250"
PROM

# 5. Prometheus 서비스 등록 및 실행 (기존 유지) [cite: 49]
cat > /etc/systemd/system/prometheus.service <<SERVICE
[Unit]
Description=Prometheus
Wants=network-online.target
After=network-online.target

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/usr/local/bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/var/lib/prometheus \
  --web.console.templates=/etc/prometheus/consoles \
  --web.console.libraries=/etc/prometheus/console_libraries
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE

chown -R prometheus:prometheus /etc/prometheus /var/lib/prometheus
systemctl daemon-reload
systemctl enable prometheus
systemctl start prometheus

# 마스터, 워커 노드 ip를 hosts.ini 파일에 자동 저장(위쪽 코드) 후 자동 실행하여 각 노드에 k3s, argoCD, istio 설치

# 1. SSH 개인키 저장 (엔서블 접속용)
cat > /home/ubuntu/ansible/id_rsa <<EOF
${ssh_private_key}
EOF
chmod 600 /home/ubuntu/ansible/id_rsa
chown ubuntu:ubuntu /home/ubuntu/ansible/id_rsa

# 2. 설치용 엔서블 플레이북 파일 생성
cat > /home/ubuntu/ansible/setup_k3s.yml <<EOF
- name: Setup K3s Cluster
  hosts: all
  become: yes
  tasks:
    - name: Wait for connection
      wait_for_connection:
        timeout: 300

    # 여기에 K3s, Istio, ArgoCD 설치 태스크들을 정의합니다.
EOF

# 3. 백그라운드에서 엔서블 실행
# (스크립트가 바로 종료되어야 테라폼 apply가 완료되므로 nohup 등을 사용합니다)
nohup sudo -u ubuntu ansible-playbook -i /home/ubuntu/ansible/hosts.ini /home/ubuntu/ansible/setup_k3s.yml --private-key=/home/ubuntu/ansible/id_rsa > /home/ubuntu/ansible/install.log 2>&1 &