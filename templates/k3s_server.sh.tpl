#!/bin/bash
set -eux

# 1. 패키지 업데이트 및 엔서블 실행을 위한 파이썬 설치
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip curl

# 2. 네트워크 연결을 위한 Tailscale 설치 및 설정
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --auth-key=${tailscale_auth_key} --hostname=k3s-server --ssh=false || true

# 💡 K3s 설치 관련 로직은 삭제되었습니다. (엔서블에서 처리 예정)