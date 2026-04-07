variable "admin_cidr" {
  description = "Admin public IP CIDR, e.g. 1.2.3.4/32"
  type        = list(string)
}

variable "tailscale_auth_key" {
  description = "Tailscale auth key"
  type        = string
  sensitive   = true
}

variable "k3s_token" {
  description = "Shared token for K3s cluster"
  type        = string
  sensitive   = true
}

variable "db_username" {
  description = "RDS master username"
  type        = string
}

variable "db_password" {
  description = "RDS master password"
  type        = string
  sensitive   = true
}

variable "ssh_key_name" {
  description = "AWS에 등록할 키 페어 이름"
  type        = string
  default     = "aiops-internal-key"
}

variable "private_dns_zone_name" {
  description = "Private Route53 hosted zone name for internal services"
  type        = string
  default     = "internal.aiops"
}

variable "local_tailscale_ip" {
  description = "Tailscale IP address for the local environment"
  type        = string
  default     = ""
}

# ------------------------------------------
# GitHub secret sync (existing)
# ------------------------------------------
variable "enable_github_secret_sync" {
  description = "Whether Terraform should automatically sync KUBECONFIG_B64 into GitHub Actions secrets"
  type        = bool
  default     = true
}

variable "github_owner" {
  description = "GitHub owner or organization name"
  type        = string
  default     = ""

  validation {
    condition     = var.enable_github_secret_sync == false || length(trimspace(var.github_owner)) > 0
    error_message = "enable_github_secret_sync=true 이면 github_owner 는 비어 있을 수 없습니다."
  }
}

variable "github_repository" {
  description = "GitHub repository name only, without owner"
  type        = string
  default     = ""

  validation {
    condition     = var.enable_github_secret_sync == false || length(trimspace(var.github_repository)) > 0
    error_message = "enable_github_secret_sync=true 이면 github_repository 는 비어 있을 수 없습니다."
  }
}

variable "github_actions_kubeconfig_secret_name" {
  description = "GitHub Actions secret name for kubeconfig"
  type        = string
  default     = "KUBECONFIG_B64"

  validation {
    condition     = length(trimspace(var.github_actions_kubeconfig_secret_name)) > 0
    error_message = "github_actions_kubeconfig_secret_name 은 비어 있을 수 없습니다."
  }
}

variable "github_secret_sync_ssm_parameter_name" {
  description = "SSM Parameter Store name containing the GitHub PAT used for syncing KUBECONFIG_B64 into GitHub Actions secrets"
  type        = string
  default     = "/zero-trust-idp/github-secret-sync-token"

  validation {
    condition     = var.enable_github_secret_sync == false || length(trimspace(var.github_secret_sync_ssm_parameter_name)) > 0
    error_message = "enable_github_secret_sync=true 이면 github_secret_sync_ssm_parameter_name 은 비어 있을 수 없습니다."
  }
}

# ------------------------------------------
# Monitoring node GitHub self-hosted runner
# ------------------------------------------
variable "enable_monitoring_github_runner" {
  description = "Whether to install and register a GitHub self-hosted runner on the monitoring node"
  type        = bool
  default     = true
}

variable "github_runner_scope" {
  description = "Runner registration scope: repo or org"
  type        = string
  default     = "repo"

  validation {
    condition     = contains(["repo", "org"], var.github_runner_scope)
    error_message = "github_runner_scope must be either 'repo' or 'org'."
  }
}

variable "github_runner_owner" {
  description = "GitHub owner or organization name used for runner registration"
  type        = string
  default     = "BongE0115"

  validation {
    condition     = var.enable_monitoring_github_runner == false || length(trimspace(var.github_runner_owner)) > 0
    error_message = "enable_monitoring_github_runner=true 이면 github_runner_owner 는 비어 있을 수 없습니다."
  }
}

variable "github_runner_repository" {
  description = "GitHub repository name used for repo-scoped runner registration"
  type        = string
  default     = "Zero-Trust-IDP"

  validation {
    condition     = var.enable_monitoring_github_runner == false || var.github_runner_scope == "org" || length(trimspace(var.github_runner_repository)) > 0
    error_message = "repo scope runner 를 사용할 때 github_runner_repository 는 비어 있을 수 없습니다."
  }
}

variable "github_runner_labels" {
  description = "Labels applied to the monitoring node self-hosted runner"
  type        = list(string)
  default     = ["monitoring-node", "linux", "internal-k8s"]
}

variable "github_runner_version" {
  description = "GitHub Actions runner version to install on the monitoring node"
  type        = string
  default     = "2.327.1"
}

variable "github_runner_token_ssm_parameter_name" {
  description = "SSM Parameter Store name containing the bootstrap token used to request a GitHub runner registration token"
  type        = string
  default     = "/zero-trust-idp/github-runner-bootstrap-token"

  validation {
    condition     = var.enable_monitoring_github_runner == false || length(trimspace(var.github_runner_token_ssm_parameter_name)) > 0
    error_message = "enable_monitoring_github_runner=true 이면 github_runner_token_ssm_parameter_name 은 비어 있을 수 없습니다."
  }
}

variable "external_python_program" {
  description = "Command used by Terraform external data source to run Python"
  type        = list(string)
  default     = ["python3"]

  validation {
    condition     = length(var.external_python_program) > 0
    error_message = "external_python_program must contain at least one element."
  }
}

variable "slack_bot_token" {
  type      = string
  sensitive = true # 
}

variable "slack_channel" {
  type = string
}