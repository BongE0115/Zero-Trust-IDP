---
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
  tasks:
    - name: Install K3s Server
      shell: curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server --write-kubeconfig-mode 644" K3S_TOKEN={{ k3s_token }} sh -
    
    - name: Wait for node-token
      wait_for:
        path: /var/lib/rancher/k3s/server/node-token

# [3단계] 워커 노드 K3s 조인
- name: Join Worker Nodes to Cluster
  hosts: k3s_worker
  become: yes
  tasks:
    - name: Join K3s Cluster
      shell: "curl -sfL https://get.k3s.io | K3S_URL=https://{{ hostvars['master']['ansible_host'] }}:6443 K3S_TOKEN={{ k3s_token }} sh -"

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

    - name: Install ArgoCD & Other Tools
      shell: |
        helm upgrade --install argocd argo/argo-cd -n argocd --create-namespace
        helm upgrade --install node-exporter prometheus-community/prometheus-node-exporter -n monitoring --create-namespace

# [5단계] Zero-Trust 보안 정책 적용 (Forensic Sandbox)
- name: Apply Zero-Trust Security Policies
  hosts: k3s_master
  become: yes
  environment:
    KUBECONFIG: /etc/rancher/k3s/k3s.yaml
  tasks:
    - name: Create and Label Sandbox Namespace
      shell: |
        kubectl create namespace forensic-sandbox --dry-run=client -o yaml | kubectl apply -f -
        # 네임스페이스를 Ambient Mesh에 참여시킴 (ztunnel 관리 영역)
        kubectl label namespace forensic-sandbox istio.io/dataplane-mode=ambient --overwrite

    # ★ [추가 권장 태스크] ★ : 샌드박스 트래픽이 Waypoint(검문소)를 반드시 거치도록 바인딩
    - name: Bind Waypoint Proxy to Namespace
      shell: |
        kubectl label namespace forensic-sandbox istio.io/use-waypoint=sandbox-waypoint --overwrite

    - name: Deploy Waypoint Proxy & Policies
      copy:
        dest: "/tmp/{{ item.name }}"
        content: "{{ item.content }}"
      with_items:
        - name: "waypoint.yaml"
          content: |
            apiVersion: gateway.networking.k8s.io/v1beta1
            kind: Gateway
            metadata:
              name: sandbox-waypoint
              namespace: forensic-sandbox
              labels:
                istio.io/waypoint-for: service
            spec:
              gatewayClassName: istio-waypoint
              listeners:
              - name: mesh
                port: 15008
                protocol: HBONE
        - name: "security-policies.yaml"
          content: |
            # 1. 외부 RDS 엔드포인트 등록
            apiVersion: networking.istio.io/v1alpha3
            kind: ServiceEntry
            metadata:
              name: aws-rds-external
              namespace: forensic-sandbox
            spec:
              hosts: ["{{ rds_endpoint }}"]
              ports: [{number: 3306, name: tcp-mysql, protocol: TCP}]
              location: MESH_EXTERNAL
              resolution: DNS
            ---
            # 2. RDS 접근 차단 정책 (L7)
            apiVersion: security.istio.io/v1beta1
            kind: AuthorizationPolicy
            metadata:
              name: deny-aws-rds-egress
              namespace: forensic-sandbox
            spec:
              selector: {matchLabels: {app: forensic-sandbox-app}}
              action: DENY
              rules:
              - to: [{operation: {hosts: ["{{ rds_endpoint }}"], ports: ["3306"]}}]
            ---
            # 3. mTLS 강제 (STRICT 모드)
            apiVersion: security.istio.io/v1beta1
            kind: PeerAuthentication
            metadata:
              name: default-strict-mtls
              namespace: forensic-sandbox
            spec:
              mtls: {mode: STRICT}

    - name: Apply Manifests
      shell: kubectl apply -f /tmp/waypoint.yaml -f /tmp/security-policies.yaml
