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

# [4단계] 플랫폼 도구 및 모니터링 연동 설치
- name: Deploy Platform Tools & Monitoring
  hosts: k3s_master
  become: yes       # <--- 필수 추가: root 권한으로 실행 (k3s.yaml 읽기 위함)
  environment:      # <--- 필수 추가: helm과 kubectl이 클러스터 접속 정보를 찾도록 길 안내
    KUBECONFIG: /etc/rancher/k3s/k3s.yaml
  tasks:
    - name: Install Helm
      shell: curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

    - name: Add Helm Repositories
      shell: |
        helm repo add argo https://argoproj.github.io/argo-helm
        helm repo add istio https://istio-release.storage.googleapis.com/charts
        helm repo add strimzi https://strimzi.io/charts/
        helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
        helm repo update

    - name: Install ArgoCD
      shell: helm upgrade --install argocd argo/argo-cd -n argocd --create-namespace

    - name: Install Istio Base & Discovery
      shell: |
        helm upgrade --install istio-base istio/base -n istio-system --create-namespace
        helm upgrade --install istiod istio/istiod -n istio-system
    
    - name: Label default namespace for Istio injection
      shell: kubectl label namespace default istio-injection=enabled --overwrite

    - name: Install Strimzi Kafka Operator
      shell: helm upgrade --install strimzi-operator strimzi/strimzi-kafka-operator -n kafka --create-namespace


    - name: Deploy Kafka NodePool (Required for Latest Strimzi)
      shell: |
        cat <<EOF | kubectl apply -f -
        apiVersion: kafka.strimzi.io/v1beta2
        kind: KafkaNodePool
        metadata:
          name: kafka-pool
          namespace: kafka
          labels:
            strimzi.io/cluster: my-cluster
        spec:
          replicas: 1
          roles:
            - broker
            - controller
          storage:
            type: ephemeral
        EOF

    - name: Deploy Lightweight Kafka Instance (KRaft Mode with NodePool)
      shell: |
        cat <<EOF | kubectl apply -f -
        apiVersion: kafka.strimzi.io/v1beta2
        kind: Kafka
        metadata:
          name: my-cluster
          namespace: kafka
          annotations:
            strimzi.io/node-pools: enabled
            strimzi.io/kraft: enabled
        spec:
          kafka:
            version: 4.1.0
            listeners:
              - name: plain
                port: 9092
                type: internal
                tls: false
              - name: controller
                port: 9093
                type: internal
                tls: false
            config:
              offsets.topic.replication.factor: 1
              transaction.state.log.replication.factor: 1
              inter.broker.protocol.version: "4.1"
            jvmOptions:
              "-Xms": "256M"
              "-Xmx": "256M"
          entityOperator:
            topicOperator: {}
            userOperator: {}
        EOF

    - name: Install Monitoring Collectors (Node Exporter & KSM)
      shell: |
        helm upgrade --install node-exporter prometheus-community/prometheus-node-exporter -n monitoring --create-namespace
        helm upgrade --install kube-state-metrics prometheus-community/kube-state-metrics -n monitoring

    - name: Extract ArgoCD Admin Password
      shell: kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
      register: argocd_password

    - name: Save Installation Info to File
      copy:
        content: |
          K3s Cluster Setup Complete.
          ArgoCD Admin Password: {{ argocd_password.stdout }}
          Istio Injection: Enabled on 'default' namespace
          Kafka Memory: Limited to 256MB
        dest: /home/ubuntu/ansible/install_summary.txt