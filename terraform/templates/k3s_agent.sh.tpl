#!/bin/bash
set -eux

# 1. 패키지 업데이트 및 엔서블 실행을 위한 파이썬 설치
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip curl

# 2. 네트워크 연결을 위한 Tailscale 설치 및 설정
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --auth-key=${tailscale_auth_key} --hostname=k3s-agent --ssh=false || true

# ---------------------------------------------------------
# [추가] 부팅 후 SSM 에이전트 강제 기상 및 상태 확정
# K3s 및 네트워크(CNI) 초기화 과정에서 에이전트 통신이 끊기는 현상 방지
# ---------------------------------------------------------

# 1. snap 데몬이 완전히 뜰 때까지 잠시 대기
sleep 10

# 2. 확실한 이름표(snap.amazon-ssm-agent...)로 서비스 활성화
systemctl enable snap.amazon-ssm-agent.amazon-ssm-agent.service

# 3. AWS 시스템 매니저로 다시 통신하라고 등 떠밀기 (재시작)
systemctl restart snap.amazon-ssm-agent.amazon-ssm-agent.service