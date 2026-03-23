apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kafka-operator-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'https://github.com/BongE0115/Zero-Trust-IDP.git'
    targetRevision: Infra
    path: 'k3s-manifests/core-infra/kafka-operator'
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: kafka
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true