#!/bin/bash
set -euxo pipefail

LOG_FILE="/var/log/monitoring-bootstrap.log"
exec > >(tee -a "$LOG_FILE") 2>&1

export DEBIAN_FRONTEND=noninteractive

echo "[INFO] installing base packages"
apt-get update -y
apt-get install -y \
  curl unzip gnupg lsb-release apt-transport-https ca-certificates \
  software-properties-common jq awscli git python3 python3-pip

echo "[INFO] installing tailscale if needed"
if ! command -v tailscale >/dev/null 2>&1; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi

systemctl enable tailscaled
systemctl restart tailscaled

if [[ -n "${tailscale_auth_key}" ]]; then
  tailscale up --authkey "${tailscale_auth_key}" || true
fi

echo "[INFO] installing ansible"
apt-add-repository --yes --update ppa:ansible/ansible || true
apt-get update -y
apt-get install -y ansible

python3 -m pip install --upgrade pip
python3 -m pip install boto3 botocore

echo "[INFO] installing session-manager-plugin if needed"
if ! command -v session-manager-plugin >/dev/null 2>&1; then
  cd /tmp
  curl -fsSLo session-manager-plugin.deb \
    "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb"
  dpkg -i session-manager-plugin.deb || apt-get install -f -y
fi

echo "[INFO] cloning gitops repo"
rm -rf /opt/gitops-repo
git clone -b "${gitops_target_revision}" "${gitops_repo_url}" /opt/gitops-repo

mkdir -p /opt/gitops-repo/ansible/inventory

cat > /opt/gitops-repo/ansible/inventory/hosts.ini <<EOF
${ansible_inventory_content}
EOF

cat > /opt/gitops-repo/ansible/ansible.cfg <<'EOF'
[defaults]
inventory = ./inventory/hosts.ini
host_key_checking = False
retry_files_enabled = False
stdout_callback = yaml
interpreter_python = auto_silent
collections_paths = ~/.ansible/collections:/usr/share/ansible/collections

[ssh_connection]
pipelining = True
EOF

echo "[INFO] decoding argocd values"
mkdir -p /opt/gitops-repo/bootstrap-runtime
printf '%s' "${argocd_values_b64}" | base64 -d > /opt/gitops-repo/bootstrap-runtime/argocd-values.yaml

cat > /opt/gitops-repo/bootstrap-runtime/argocd-extra-vars.yml <<EOF
aws_region: "${aws_region}"
gitops_repo_url: "${gitops_repo_url}"
gitops_target_revision: "${gitops_target_revision}"
local_tailscale_ip: "${local_tailscale_ip}"
argocd_values_content: |
$(sed 's/^/  /' /opt/gitops-repo/bootstrap-runtime/argocd-values.yaml)
EOF

# 핵심 수정 포인트: 복잡한 명령줄 옵션 대신 Ansible 변수 파일을 동적으로 생성
echo "[INFO] creating monitoring variables file"
cat > /opt/gitops-repo/bootstrap-runtime/monitoring-vars.yml <<'EOF'
aws_region: "${aws_region}"
tailscale_auth_key: "${tailscale_auth_key}"
enable_monitoring_github_runner: "${enable_monitoring_github_runner}"
github_runner_scope: "${github_runner_scope}"
github_runner_owner: "${github_runner_owner}"
github_runner_repository: "${github_runner_repository}"
github_runner_labels: "${github_runner_labels_csv}"
github_runner_version: "${github_runner_version}"
github_runner_token_ssm_parameter: "${github_runner_token_ssm_parameter}"
k3s_server_private_ip: "${k3s_server_private_ip}"
k3s_agent_private_ip: "${k3s_agent_private_ip}"
EOF

cd /opt/gitops-repo/ansible

echo "[INFO] installing ansible collections"
export HOME=/root
COLLECTION_PATH="/root/.ansible/collections"
mkdir -p "$COLLECTION_PATH"
if [ -f requirements.yml ]; then
  ansible-galaxy collection install -r requirements.yml -p "$COLLECTION_PATH" --force
else
  ansible-galaxy collection install amazon.aws community.aws -p "$COLLECTION_PATH" --force
fi

echo "[INFO] running monitoring-local.yml"
ANSIBLE_CONFIG=/opt/gitops-repo/ansible/ansible.cfg \
ansible-playbook monitoring-local.yml \
  -i "localhost," \
  -c local \
  -e @/opt/gitops-repo/bootstrap-runtime/monitoring-vars.yml

echo "[INFO] running k3s-server-remote.yml"
ANSIBLE_CONFIG=/opt/gitops-repo/ansible/ansible.cfg \
ansible-playbook k3s-server-remote.yml \
  -e aws_region="${aws_region}" \
  -e k3s_token="${k3s_token}" \
  -e frontend_addr="${frontend_addr}" \
  -e slack_bot_token="${slack_bot_token}" \
  -e slack_channel="${slack_channel}"

echo "[INFO] running k3s-agent-remote.yml"
ANSIBLE_CONFIG=/opt/gitops-repo/ansible/ansible.cfg \
ansible-playbook k3s-agent-remote.yml \
  -e aws_region="${aws_region}" \
  -e k3s_token="${k3s_token}"

echo "[INFO] running argocd-bootstrap.yml"
ANSIBLE_CONFIG=/opt/gitops-repo/ansible/ansible.cfg \
ansible-playbook argocd-bootstrap.yml \
  -e @/opt/gitops-repo/bootstrap-runtime/argocd-extra-vars.yml

echo "[INFO] Monitoring bootstrap completed successfully."