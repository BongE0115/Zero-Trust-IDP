# ---------------------------------------------------------
# 1. 모든 노드 공통 준비
# ---------------------------------------------------------
- name: Prepare all nodes for K3s
  hosts: all
  become: yes
  tasks:
    - name: Wait for connection
      wait_for_connection:
        timeout: 300

    - name: Create 2GB swap file if not exists
      shell: |
        if [ ! -f /swapfile ]; then
          fallocate -l 2G /swapfile
          chmod 600 /swapfile
          mkswap /swapfile
          swapon /swapfile
          echo '/swapfile none swap sw 0 0' >> /etc/fstab
        fi

    - name: Install basic packages
      apt:
        name:
          - curl
          - python3-pip
          - nfs-common
        state: present
        update_cache: yes

# ---------------------------------------------------------
# 2. K3s Master 설치
# ---------------------------------------------------------
- name: Install K3s Master
  hosts: k3s_master
  become: yes
  vars:
    k3s_version: "v1.33.9+k3s1"
  tasks:
    - name: Install K3s Server (disable traefik)
      shell: |
        curl -sfL https://get.k3s.io | \
        INSTALL_K3S_VERSION="{{ k3s_version }}" \
        INSTALL_K3S_EXEC="server --write-kubeconfig-mode 644 --disable traefik" \
        K3S_TOKEN="{{ k3s_token }}" sh -
      args:
        executable: /bin/bash

    - name: Wait for node-token
      wait_for:
        path: /var/lib/rancher/k3s/server/node-token
        timeout: 300

    - name: Wait for kubeconfig
      wait_for:
        path: /etc/rancher/k3s/k3s.yaml
        timeout: 300

    - name: Wait until Kubernetes API is responsive
      shell: kubectl get nodes
      environment:
        KUBECONFIG: /etc/rancher/k3s/k3s.yaml
      register: k3s_api_check
      retries: 20
      delay: 15
      until: k3s_api_check.rc == 0
      changed_when: false

# ---------------------------------------------------------
# 3. Worker 노드 조인
# ---------------------------------------------------------
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
      args:
        executable: /bin/bash

# ---------------------------------------------------------
# 4. ArgoCD bootstrap
# ---------------------------------------------------------
- name: Install and Bootstrap ArgoCD
  hosts: k3s_master
  become: yes
  environment:
    KUBECONFIG: /etc/rancher/k3s/k3s.yaml
  vars:
    argocd_chart_version: "8.0.0"   # 반드시 argocd-app.yaml과 동일 버전으로 맞출 것
    bootstrap_local_root: "/home/ubuntu/ansible/gitops/bootstrap"
    bootstrap_remote_root: "/opt/gitops/bootstrap"
    argocd_values_file: "/opt/gitops/bootstrap/argocd/values.yaml"

  tasks:
    - name: Install Helm if not present
      shell: |
        if ! command -v helm >/dev/null 2>&1; then
          curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
        fi
      args:
        executable: /bin/bash

    - name: Add Argo Helm repository
      shell: |
        helm repo add argo https://argoproj.github.io/argo-helm
        helm repo update
      args:
        executable: /bin/bash

    - name: Ensure bootstrap remote directory exists
      file:
        path: "{{ bootstrap_remote_root }}/argocd"
        state: directory
        mode: "0755"

    - name: Copy ArgoCD values.yaml from monitoring node to master
      copy:
        src: "{{ bootstrap_local_root }}/argocd/values.yaml"
        dest: "{{ argocd_values_file }}"
        mode: "0644"

    - name: Install ArgoCD with declarative values
      shell: |
        helm upgrade --install argocd argo/argo-cd \
          --version "{{ argocd_chart_version }}" \
          -n argocd \
          --create-namespace \
          -f "{{ argocd_values_file }}"
      args:
        executable: /bin/bash

    - name: Wait for ArgoCD server rollout
      shell: kubectl -n argocd rollout status deployment/argocd-server --timeout=300s
      args:
        executable: /bin/bash

    - name: Wait for ArgoCD repo-server rollout
      shell: kubectl -n argocd rollout status deployment/argocd-repo-server --timeout=300s
      args:
        executable: /bin/bash

    - name: Wait for ArgoCD application-controller rollout
      shell: kubectl -n argocd rollout status statefulset/argocd-application-controller --timeout=300s
      args:
        executable: /bin/bash

    - name: Wait for ArgoCD initial admin secret
      shell: kubectl get secret -n argocd argocd-initial-admin-secret
      register: argocd_secret_check
      retries: 20
      delay: 15
      until: argocd_secret_check.rc == 0
      changed_when: false