# [1단계] 모든 노드 공통 설정: 자원 최적화 및 기초 환경
- name: Prepare all nodes for K3s
  hosts: all
  become: yes
  tasks:
    - name: Create 2GB Swap file (Essential for t3.micro stability)
      shell: |
        if [ ! -f /swapfile ]; then
          fallocate -l 2G /swapfile
          chmod 600 /swapfile
          mkswap /swapfile
          swapon /swapfile
          echo '/swapfile none swap sw 0 0' >> /etc/fstab
        fi

    - name: Wait for connection (Ensuring nodes are up)
      wait_for_connection:
        timeout: 300

    - name: Install basic packages
      apt:
        name: [curl, python3-pip, nfs-common]
        state: present
        update_cache: yes

# [2단계] 마스터 노드 K3s 설치 및 구성
- name: Install K3s Master
  hosts: k3s_master
  become: yes
  vars:
    k3s_version: "v1.33.9+k3s1"
  tasks:
    - name: Install K3s Server
      shell: |
        curl -sfL https://get.k3s.io | \
        INSTALL_K3S_VERSION="{{ k3s_version }}" \
        INSTALL_K3S_EXEC="server --write-kubeconfig-mode 644" \
        K3S_TOKEN="{{ k3s_token }}" sh -

    - name: Wait for node-token
      wait_for:
        path: /var/lib/rancher/k3s/server/node-token

# [3단계] 워커 노드 K3s 조인
- name: Join Worker Nodes to Cluster
  hosts: k3s_worker
  become: yes
  vars:
    k3s_version: "v1.33.9+k3s1"
  tasks:
    - name: Join K3s Cluster
      shell: |
        curl -sfL https://get.k3s.io | \
        INSTALL_K3S_VERSION="{{ k3s_version }}" \
        K3S_URL="https://{{ hostvars['master']['ansible_host'] }}:6443" \
        K3S_TOKEN="{{ k3s_token }}" sh -

# [4단계] 플랫폼 도구 및 Istio Ambient Mesh 설치
- name: Deploy Platform Tools & Ambient Mesh
  hosts: k3s_master
  become: yes
  environment:
    KUBECONFIG: /etc/rancher/k3s/k3s.yaml
  tasks:
    - name: Install Helm
      shell: curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

    - name: Add Helm Repositories
      shell: |
        helm repo add argo https://argoproj.github.io/argo-helm
        helm repo add istio https://istio-release.storage.googleapis.com/charts
        helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
        helm repo update

    # Waypoint Proxy 운영을 위한 Kubernetes 표준 Gateway API CRD 설치
    - name: Install Kubernetes Gateway API CRDs
      shell: kubectl kustomize "github.com/kubernetes-sigs/gateway-api/config/crd?ref=v1.0.0" | kubectl apply -f -

    - name: Install Istio Base
      shell: helm upgrade --install istio-base istio/base -n istio-system --create-namespace

    # K3s 특유의 CNI 경로(/var/lib/rancher/k3s/...)를 지정하여 Ambient Mesh 활성화
    - name: Install Istio CNI (K3s specific paths)
      shell: |
        helm upgrade --install istio-cni istio/cni -n istio-system \
          --set profile=ambient \
          --set cni.cniBinDir=/var/lib/rancher/k3s/data/current/bin \
          --set cni.cniConfDir=/etc/cni/net.d

    - name: Install Istiod (Ambient Profile)
      shell: helm upgrade --install istiod istio/istiod -n istio-system --set profile=ambient

    - name: Install Ztunnel (Node Proxy)
      shell: helm upgrade --install ztunnel istio/ztunnel -n istio-system

    # Sandbox용 AWS RDS 별명(DNS) 미리 등록하기
    - name: Create Forensic Sandbox Namespace
      shell: kubectl create namespace forensic-sandbox
      ignore_errors: yes

    - name: Create RDS ExternalName Service
      shell: |
        cat <<EOF | kubectl apply -f -
        apiVersion: v1
        kind: Service
        metadata:
          name: aws-rds-host
          namespace: forensic-sandbox
        spec:
          type: ExternalName
          externalName: ${ rds_endpoint }
        EOF

    - name: Install ArgoCD & Other Tools
      shell: |
        helm upgrade --install argocd argo/argo-cd -n argocd --create-namespace
        helm upgrade --install node-exporter prometheus-community/prometheus-node-exporter -n monitoring --create-namespace

    - name: Wait for ArgoCD server rollout
      shell: kubectl -n argocd rollout status deployment/argocd-server --timeout=300s