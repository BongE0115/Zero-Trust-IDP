apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: forensic-sandbox
  namespace: argocd
spec:
  project: default
  source:
    # 1. 깃허브 저장소 주소 (테라폼에서 주입하거나 직접 수정)
    repoURL: 'https://github.com/BongE0115/Zero-Trust-IDP.git'
    
    # 2. 브랜치명 (Kafka 설정과 동일하게 Infra 브랜치 권장)
    targetRevision: Infra
    
    # 3. 감시할 폴더 경로 (새로운 구조 반영)
    # 수정 전: k8s-manifests/forensic-sandbox
    # 수정 후: 실제 저장소 루트 기준 경로 확인
    path: 'k3s-manifests/forensic-sandbox'
    
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: forensic-sandbox
    
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true

# K8s에 ArgoCD 지시서 전달하기 
# 터미널에서 딱 한 번만 실행
# kubectl apply -f argo-apps/forensic-sandbox-app.yaml


# 앰비언트 메시(Ambient Mesh) 자동 주입 확인
# forensic-sandbox 네임스페이스의 앰비언트 메시 상태 확인
# istioctl ztunnel-config workloads -n forensic-sandbox