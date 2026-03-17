output "monitoring_public_ip" {
  value = aws_instance.monitoring_server.public_ip
}

output "k3s_server_private_ip" {
  value = aws_instance.k3s_server.private_ip
}

output "k3s_agent_private_ip" {
  value = aws_instance.k3s_agent.private_ip
}

output "alb_dns_name" {
  description = "ALB의 DNS 주소"
  value       = aws_lb.aiops_alb.dns_name
}

output "rds_endpoint" {
  description = "PostgreSQL RDS 엔드포인트"
  value       = aws_db_instance.aiops_rds.endpoint
}