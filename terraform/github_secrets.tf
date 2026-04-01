terraform {
  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
    external = {
      source  = "hashicorp/external"
      version = "~> 2.3"
    }
  }
}

provider "github" {
  owner = var.github_owner
  token = var.enable_github_secret_sync ? nonsensitive(data.aws_ssm_parameter.github_secret_sync_token[0].value) : ""
}

data "aws_ssm_parameter" "github_secret_sync_token" {
  count           = var.enable_github_secret_sync ? 1 : 0
  name            = var.github_secret_sync_ssm_parameter_name
  with_decryption = true
}

data "external" "k3s_kubeconfig_b64" {
  count = var.enable_github_secret_sync ? 1 : 0

  program = [
    "python3",
    "${path.module}/scripts/get_k3s_kubeconfig.py"
  ]

  query = {
    instance_id     = aws_instance.k3s_server.id
    region          = data.aws_region.current.id
    api_server_host = aws_instance.k3s_server.private_ip
  }

  depends_on = [
    aws_instance.k3s_server
  ]
}

resource "github_actions_secret" "kubeconfig_b64" {
  count = var.enable_github_secret_sync ? 1 : 0

  repository      = var.github_repository
  secret_name     = var.github_actions_kubeconfig_secret_name
  plaintext_value = data.external.k3s_kubeconfig_b64[0].result.kubeconfig_b64
}