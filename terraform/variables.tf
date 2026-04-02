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
  default     = "" # destroy 목적이므로 빈 문자열이나 임의의 더미(dummy) 값을 넣어도 무방합니다.
}

## kubeconfig 전용

variable "enable_github_secret_sync" {
  description = "Whether Terraform should automatically sync KUBECONFIG_B64 into GitHub Actions secrets"
  type        = bool
  default     = false
}

variable "github_owner" {
  description = "GitHub owner or organization name"
  type        = string
  default     = ""
}

variable "github_repository" {
  description = "GitHub repository name only, without owner"
  type        = string
  default     = ""
}

variable "github_token" {
  description = "GitHub token with permission to manage repository Actions secrets"
  type        = string
  sensitive   = true
  default     = ""
}

variable "github_actions_kubeconfig_secret_name" {
  description = "GitHub Actions secret name for kubeconfig"
  type        = string
  default     = "KUBECONFIG_B64"
}

variable "github_secret_sync_ssm_parameter_name" {
  description = "SSM Parameter Store name containing the GitHub PAT used for syncing KUBECONFIG_B64 into GitHub Actions secrets"
  type        = string
  default     = "/zero-trust-idp/github-secret-sync-token"
}