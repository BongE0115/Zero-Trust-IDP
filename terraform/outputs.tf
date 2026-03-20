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

output "argocd_access_info" {
  description = "ArgoCD 접속 정보 및 비밀번호 확인 가이드"
  value = <<EOF

=========================================================
🚀 인프라 프로비저닝 완료! (약 3~5분 뒤부터 접속 가능합니다)
=========================================================

🔗 [ArgoCD 웹 UI 주소] 
아래 주소를 브라우저에 복사하세요 (최초 접속 시 http 사용)
http://${aws_lb.aiops_alb.dns_name}

🔑 [ArgoCD 초기 비밀번호 확인 방법]
설치가 완료된 후, 모니터링 서버(SSM)에 접속하여 아래 명령어를 입력하세요:
cat /home/ubuntu/ansible/argocd_password.txt

=========================================================
EOF
}