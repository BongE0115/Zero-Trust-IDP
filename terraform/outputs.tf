output "monitoring_public_ip" {
  value = aws_instance.monitoring_server.public_ip
}

output "k3s_server_private_ip" {
  value = aws_instance.k3s_server.private_ip
}

output "k3s_agent_private_ip" {
  value = aws_instance.k3s_agent.private_ip
}