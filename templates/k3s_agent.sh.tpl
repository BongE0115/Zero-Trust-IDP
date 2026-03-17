#!/bin/bash
set -eux

apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip curl

curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --auth-key=${tailscale_auth_key} --hostname=k3s-agent --ssh=false || true

curl -sfL https://get.k3s.io | K3S_URL="https://${k3s_server_ip}:6443" K3S_TOKEN="${k3s_token}" sh -
systemctl enable k3s-agent
systemctl start k3s-agent