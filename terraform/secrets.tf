resource "kubernetes_secret" "github_dispatch" {
  metadata {
    name      = "github-dispatch-secret"
    namespace = "kafka-poc"
  }

  data = {
    token = var.github_dispatch_token
  }

  type = "Opaque"
}