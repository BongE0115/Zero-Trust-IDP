# ==================================================
# 로컬 인프라 (On-Premise) 연동 및 자동 실행 설정
# ==================================================

resource "local_file" "local_node_setup_script" {
  filename        = "${path.module}/setup_local_env.sh"
  file_permission = "0755"

  # file 함수를 사용해 외부 스크립트를 그대로 읽어옴 (인터폴레이션 시도 안 함)
  content = file("${path.module}/templates/setup_local_env.sh")
}

# [자동화 옵션] 환경 변수를 통해 테라폼 변수를 스크립트에 전달
resource "null_resource" "auto_run_setup" {
  depends_on = [local_file.local_node_setup_script]

  provisioner "local-exec" {
    command = "sudo ./setup_local_env.sh"

    # 모든 테라폼 변수를 셸 환경 변수로 주입
    environment = {
      TF_VAR_AWS_REGION    = var.aws_region
      TF_VAR_PROJECT_NAME  = var.project_name
      TF_VAR_AWS_IP        = aws_instance.k3s_server.private_ip
      TF_VAR_FRONTEND_DNS  = aws_lb.aiops_alb.dns_name
    }
  }
}