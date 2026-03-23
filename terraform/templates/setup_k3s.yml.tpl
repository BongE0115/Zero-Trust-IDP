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
        helm repo add strimzi https://strimzi.io/charts/
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

   
    # Kafka 인프라를 위한 Strimzi Operator 사전 설치
    
    - name: Create Kafka Namespace
      shell: kubectl create namespace kafka
      ignore_errors: yes  # 이미 네임스페이스가 있어도 에러 내지 않고 패스

    - name: Install Strimzi Operator (CRDs pinned to version)
      shell: |
        helm upgrade --install strimzi strimzi/strimzi-kafka-operator \
          --namespace kafka --create-namespace \
          --version 0.43.0  # k3s-manifests\core-infra 내 kafka 관련 deploy 코드 버전에 따라 오퍼레이터 버전을 수정하면 됨.
    
    
    # Sandbox용 AWS RDS 별명(DNS) 미리 등록하기
    
    - name: Create Forensic Sandbox Namespace
      shell: kubectl create namespace forensic-sandbox
      ignore_errors: yes  # 이미 있어도 에러 무시

    - name: Create RDS ExternalName Service
      shell: |
        cat <<EOF | kubectl apply -f -
        apiVersion: v1
        kind: Service
        metadata:
          name: aws-rds-host  # 우리가 정한 별명
          namespace: forensic-sandbox
        spec:
          type: ExternalName
          externalName: ${ rds_endpoint } # outputs.tf rds_address를 main에서 모니터링 서버 user_data를 통해 서버 안으로 집어 넣고, 마스터 노드에서 실행될 setup_k3s 파일의 변수로 사용한다.  
        EOF

    - name: Install ArgoCD & Other Tools
      shell: |
        helm upgrade --install argocd argo/argo-cd -n argocd --create-namespace
        helm upgrade --install node-exporter prometheus-community/prometheus-node-exporter -n monitoring --create-namespace