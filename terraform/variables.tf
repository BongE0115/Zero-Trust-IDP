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
<<<<<<< HEAD
=======

variable "github_dispatch_token" {
  description = "GitHub PAT for workflow dispatch"
  type        = string
  sensitive   = true
}

variable "local_tailscale_ip" {
  description = "로컬 워커 노드의 Tailscale IP 주소"
  type        = string
} 
>>>>>>> 23053f297f1cd07d15a9fc870c0bd38d516137bc
