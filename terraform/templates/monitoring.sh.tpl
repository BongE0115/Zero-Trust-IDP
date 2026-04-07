#!/bin/bash
set -euxo pipefail

LOG_FILE="/var/log/monitoring-bootstrap.log"
exec > >(tee -a "$LOG_FILE") 2>&1

AWS_REGION="${aws_region}"
TAILSCALE_AUTH_KEY="${tailscale_auth_key}"

GITOPS_REPO_URL="${gitops_repo_url}"
GITOPS_TARGET_REVISION="${gitops_target_revision}"

ENABLE_MONITORING_GITHUB_RUNNER="${enable_monitoring_github_runner}"
GITHUB_RUNNER_SCOPE="${github_runner_scope}"
GITHUB_RUNNER_OWNER="${github_runner_owner}"
GITHUB_RUNNER_REPOSITORY="${github_runner_repository}"
GITHUB_RUNNER_LABELS="${github_runner_labels_csv}"
GITHUB_RUNNER_VERSION="${github_runner_version}"
GITHUB_RUNNER_TOKEN_SSM_PARAMETER="${github_runner_token_ssm_parameter}"

K3S_TOKEN="${k3s_token}"
FRONTEND_ADDR="${frontend_addr}"
SLACK_BOT_TOKEN="${slack_bot_token}"
SLACK_CHANNEL="${slack_channel}"

ARGOCD_VALUES_B64="${argocd_values_b64}"

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

if [[ -n "$${TAILSCALE_AUTH_KEY:-}" ]]; then
  tailscale up --authkey "$${TAILSCALE_AUTH_KEY}" || true
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
git clone -b "$${GITOPS_TARGET_REVISION}" "$${GITOPS_REPO_URL}" /opt/gitops-repo

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
printf '%s' "$${ARGOCD_VALUES_B64}" | base64 -d > /opt/gitops-repo/bootstrap-runtime/argocd-values.yaml

cat > /opt/gitops-repo/bootstrap-runtime/argocd-extra-vars.yml <<EOF
aws_region: "$${AWS_REGION}"
gitops_repo_url: "$${GITOPS_REPO_URL}"
gitops_target_revision: "$${GITOPS_TARGET_REVISION}"
argocd_values_content: |
$(sed 's/^/  /' /opt/gitops-repo/bootstrap-runtime/argocd-values.yaml)
EOF

cd /opt/gitops-repo/ansible

echo "[INFO] installing ansible collections"
if [ -f requirements.yml ]; then
  ansible-galaxy collection install -r requirements.yml --force
else
  ansible-galaxy collection install amazon.aws community.aws --force
fi

echo "[INFO] running monitoring-local.yml"
ANSIBLE_CONFIG=/opt/gitops-repo/ansible/ansible.cfg \
ansible-playbook monitoring-local.yml \
  -i "localhost," \
  -c local \
  -e aws_region="$${AWS_REGION}" \
  -e tailscale_auth_key="$${TAILSCALE_AUTH_KEY}" \
  -e enable_monitoring_github_runner="$${ENABLE_MONITORING_GITHUB_RUNNER}" \
  -e github_runner_scope="$${GITHUB_RUNNER_SCOPE}" \
  -e github_runner_owner="$${GITHUB_RUNNER_OWNER}" \
  -e github_runner_repository="$${GITHUB_RUNNER_REPOSITORY}" \
  -e github_runner_labels="$${GITHUB_RUNNER_LABELS}" \
  -e github_runner_version="$${GITHUB_RUNNER_VERSION}" \
  -e github_runner_token_ssm_parameter="$${GITHUB_RUNNER_TOKEN_SSM_PARAMETER}" \
  -e k3s_server_private_ip="${aws_instance.k3s_server.private_ip}" \
  -e k3s_agent_private_ip="${aws_instance.k3s_agent.private_ip}" 

echo "[INFO] running k3s-server-remote.yml"
ANSIBLE_CONFIG=/opt/gitops-repo/ansible/ansible.cfg \
ansible-playbook k3s-server-remote.yml \
  -e aws_region="$${AWS_REGION}" \
  -e k3s_token="$${K3S_TOKEN}" \
  -e frontend_addr="$${FRONTEND_ADDR}" \
  -e slack_bot_token="$${SLACK_BOT_TOKEN}" \
  -e slack_channel="$${SLACK_CHANNEL}"

echo "[INFO] running k3s-agent-remote.yml"
ANSIBLE_CONFIG=/opt/gitops-repo/ansible/ansible.cfg \
ansible-playbook k3s-agent-remote.yml \
  -e aws_region="$${AWS_REGION}" \
  -e k3s_token="$${K3S_TOKEN}"

echo "[INFO] running argocd-bootstrap.yml"
ANSIBLE_CONFIG=/opt/gitops-repo/ansible/ansible.cfg \
ansible-playbook argocd-bootstrap.yml \
  -e @/opt/gitops-repo/bootstrap-runtime/argocd-extra-vars.yml

echo "[INFO] Monitoring bootstrap completed successfully."