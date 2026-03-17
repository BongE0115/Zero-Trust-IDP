variable "admin_cidr" {
  description = "Admin public IP CIDR, e.g. 1.2.3.4/32"
  type        = string
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