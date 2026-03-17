#!/bin/bash
set -eux

apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3 python3-pip curl unzip gnupg lsb-release apt-transport-https ca-certificates software-properties-common

apt-get install -y ansible

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

mkdir -p /etc/prometheus /var/lib/prometheus
cp prometheus-2.54.1.linux-amd64/prometheus /usr/local/bin/
cp prometheus-2.54.1.linux-amd64/promtool /usr/local/bin/
cp -r prometheus-2.54.1.linux-amd64/consoles /etc/prometheus
cp -r prometheus-2.54.1.linux-amd64/console_libraries /etc/prometheus

cat > /etc/prometheus/prometheus.yml <<PROM
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]

  - job_name: "k3s-nodes"
    static_configs:
      - targets:
          - "${k3s_server_private_ip}:10250"
          - "${k3s_agent_private_ip}:10250"
PROM

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