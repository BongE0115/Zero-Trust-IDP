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

# 2-3. Ansible 환경 설정 (SSH 키 위치 고정 및 호스트 체크 무시)
cat > /home/ubuntu/ansible/ansible.cfg <<EOF
[defaults]
inventory = ./hosts.ini
private_key_file = ./id_rsa
host_key_checking = False
EOF

chown -R ubuntu:ubuntu /home/ubuntu/ansible

# ---------------------------------------------------------
# 3. Grafana & Prometheus 설치 (기존 유지)
# ---------------------------------------------------------
# Grafana 설치 
mkdir -p /etc/apt/keyrings
curl -fsSL https://apt.grafana.com/gpg.key | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" > /etc/apt/sources.list.d/grafana.list
apt-get update -y
apt-get install -y grafana
systemctl enable grafana-server
systemctl start grafana-server

# Prometheus 설치 및 설정
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
EOF

chown -R prometheus:prometheus /etc/prometheus
chown -R prometheus:prometheus /var/lib/prometheus

# Prometheus 서비스 등록 및 실행 
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

# 4-1. 설치용 엔서블 플레이북 파일 생성 

# setup_k3s 파일 생성
cat <<'EOF' > /home/ubuntu/ansible/setup_k3s.yml
${ansible_playbook_content}
EOF

# kafka용 아르고cd 어플리케이션 파일 생성
cat <<'EOF' > /home/ubuntu/ansible/argocd-app.yml
${argocd_app_content}
EOF

# 샌드박스용 아르고 cd 어플리케이션 파일 생성
cat <<'EOF' > /home/ubuntu/ansible/forensic-sandbox-app.yml
${forensic_sandbox_app_content}
EOF

# ★ 전체 파일 소유권을 한 번에 확실하게 변경 (오타/누락 방지)
chown -R ubuntu:ubuntu /home/ubuntu/ansible

# 4-2. 엔서블 실행 (동기 방식: 설치 완료까지 대기)
cd /home/ubuntu/ansible

# ★ 로그 파일 미리 생성 (권한 꼬임 방지)
sudo -u ubuntu touch install.log

# 1단계: k3s 및 argocd 기초 설치 (Ansible 실행)
# (주의: '>' 대신 '>>'를 써야 기존 로그가 지워지지 않고 누적됩니다)
sudo -u ubuntu ansible-playbook -i hosts.ini setup_k3s.yml >> install.log 2>&1

# 2단계: ArgoCD ALB 연동을 위한 Insecure 모드 설정 및 재시작
sudo -u ubuntu ssh -i /home/ubuntu/ansible/id_rsa -o StrictHostKeyChecking=no ubuntu@${k3s_server_private_ip} "sudo k3s kubectl patch configmap argocd-cmd-params-cm -n argocd -p '{\"data\": {\"server.insecure\": \"true\"}}'" >> install.log 2>&1
sudo -u ubuntu ssh -i /home/ubuntu/ansible/id_rsa -o StrictHostKeyChecking=no ubuntu@${k3s_server_private_ip} "sudo k3s kubectl rollout restart deployment argocd-server -n argocd" >> install.log 2>&1

# 3단계: ArgoCD 서비스를 NodePort 타입으로 변경하고 포트를 30080으로 고정
sudo -u ubuntu ssh -i /home/ubuntu/ansible/id_rsa -o StrictHostKeyChecking=no ubuntu@${k3s_server_private_ip} \
  "sudo k3s kubectl patch svc argocd-server -n argocd --patch '{\"spec\": {\"type\": \"NodePort\", \"ports\": [{\"port\": 80, \"nodePort\": 30080}]}}'" >> install.log 2>&1
  
# (선택사항) 기존에 생성된 ingress가 있다면 혼란을 줄 수 있으므로 삭제
sudo -u ubuntu ssh -i /home/ubuntu/ansible/id_rsa -o StrictHostKeyChecking=no ubuntu@${k3s_server_private_ip} \
  "sudo k3s kubectl delete ingress argocd-ingress -n argocd || true" >> install.log 2>&1
  
# 4단계: 아르고CD에게 깃허브 지시서 전달 (kafka용)
sudo -u ubuntu scp -i /home/ubuntu/ansible/id_rsa -o StrictHostKeyChecking=no /home/ubuntu/ansible/argocd-app.yml ubuntu@${k3s_server_private_ip}:/tmp/argocd-app.yml
sudo -u ubuntu ssh -i /home/ubuntu/ansible/id_rsa -o StrictHostKeyChecking=no ubuntu@${k3s_server_private_ip} "sudo k3s kubectl apply -f /tmp/argocd-app.yml" >> install.log 2>&1

# 5단계: 아르고CD에게 깃허브 지시서 전달 (sandbox용)
sudo -u ubuntu scp -i /home/ubuntu/ansible/id_rsa -o StrictHostKeyChecking=no /home/ubuntu/ansible/forensic-sandbox-app.yml ubuntu@${k3s_server_private_ip}:/tmp/forensic-sandbox-app.yml
sudo -u ubuntu ssh -i /home/ubuntu/ansible/id_rsa -o StrictHostKeyChecking=no ubuntu@${k3s_server_private_ip} "sudo k3s kubectl apply -f /tmp/forensic-sandbox-app.yml" >> install.log 2>&1

# ★ [시니어의 안전장치] 6단계 전, ArgoCD Secret이 만들어질 때까지 대기
echo "Waiting for ArgoCD initial secret to be generated..." >> install.log
for i in {1..20}; do
  if sudo -u ubuntu ssh -i /home/ubuntu/ansible/id_rsa -o StrictHostKeyChecking=no ubuntu@${k3s_server_private_ip} "sudo k3s kubectl get secret -n argocd argocd-initial-admin-secret" > /dev/null 2>&1; then
    echo "ArgoCD Secret Found!" >> install.log
    break
  fi
  echo "Still waiting for ArgoCD... ($i/20)" >> install.log
  sleep 15
done

# 6단계: 앤서블이 끝난 직후, ArgoCD 비밀번호를 모니터링 서버로 추출
sudo -u ubuntu ssh -i /home/ubuntu/ansible/id_rsa -o StrictHostKeyChecking=no ubuntu@${k3s_server_private_ip} "sudo k3s kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d" > /home/ubuntu/ansible/argocd_password.txt

# ★ 최종적으로 생성된 비번 파일과 로그 파일의 소유권 재확인
chown -R ubuntu:ubuntu /home/ubuntu/ansible