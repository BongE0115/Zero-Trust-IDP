# argocd-app.yml.tpl
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kafka-infra-auto
  namespace: argocd
spec:
  project: default
  source:
    # 1. 감시할 깃허브 저장소 주소 (Public이라 인증 불필요)
    repoURL: 'https://github.com/BongE0115/Zero-Trust-IDP.git'
    # 2. 감시할 브랜치명 (중요: Infra 브랜치)
    targetRevision: Infra
    # 3. kafka 설계도가 들어있는 폴더 경로 (레포지토리 루트 기준)
    path: 'k3s-mainfests/core-infra'
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: kafka
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true