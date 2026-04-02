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

locals {
  github_owner_trimmed      = trimspace(var.github_owner)
  github_repository_trimmed = trimspace(var.github_repository)
  github_secret_name_trimmed = trimspace(var.github_actions_kubeconfig_secret_name)
  github_sync_token = var.enable_github_secret_sync
    ? trimspace(nonsensitive(data.aws_ssm_parameter.github_secret_sync_token[0].value))
    : ""
}

provider "github" {
  owner = local.github_owner_trimmed
  token = local.github_sync_token
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

  repository      = local.github_repository_trimmed
  secret_name     = local.github_secret_name_trimmed
  plaintext_value = data.external.k3s_kubeconfig_b64[0].result.kubeconfig_b64

  lifecycle {
    precondition {
      condition     = length(local.github_owner_trimmed) > 0
      error_message = "enable_github_secret_sync=true 인데 github_owner 가 비어 있습니다."
    }

    precondition {
      condition     = length(local.github_repository_trimmed) > 0
      error_message = "enable_github_secret_sync=true 인데 github_repository 가 비어 있습니다."
    }

    precondition {
      condition     = length(local.github_secret_name_trimmed) > 0
      error_message = "github_actions_kubeconfig_secret_name 이 비어 있습니다."
    }

    precondition {
      condition     = length(local.github_sync_token) > 0
      error_message = "SSM 에서 읽은 GitHub PAT 가 비어 있습니다. github_secret_sync_ssm_parameter_name 을 확인하세요."
    }

    precondition {
      condition     = can(data.external.k3s_kubeconfig_b64[0].result.kubeconfig_b64) && length(trimspace(data.external.k3s_kubeconfig_b64[0].result.kubeconfig_b64)) > 0
      error_message = "k3s kubeconfig base64 생성에 실패했습니다. get_k3s_kubeconfig.py 또는 k3s_server/SSM 상태를 확인하세요."
    }
  }
}