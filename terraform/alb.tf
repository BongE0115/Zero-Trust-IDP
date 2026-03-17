# ==========================================
# ALB
# ==========================================
resource "aws_lb" "aiops_alb" {
  name                       = "aiops-alb"
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb_sg.id]
  subnets                    = [aws_subnet.public_a.id, aws_subnet.public_b.id]
  enable_deletion_protection = false

  tags = {
    Name      = "aiops-alb"
    Project   = "AIOps"
    ManagedBy = "Terraform"
  }
}

# ==========================================
# Target Group
# ==========================================
resource "aws_lb_target_group" "aiops_tg" {
  name     = "aiops-tg"
  port     = 80
  protocol = "HTTP"
  vpc_id   = aws_vpc.main.id

  health_check {
    interval            = 30
    path                = "/"
    port                = "80"
    protocol            = "HTTP"
    timeout             = 5
    healthy_threshold   = 3
    unhealthy_threshold = 3
  }

  tags = {
    Name      = "aiops-tg"
    Project   = "AIOps"
    ManagedBy = "Terraform"
  }
}

# ==========================================
# HTTP Listener
# ==========================================
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.aiops_alb.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.aiops_tg.arn
  }
}

# ==========================================
# Target Attachments
# ==========================================
resource "aws_lb_target_group_attachment" "k3s_server_attachment" {
  target_group_arn = aws_lb_target_group.aiops_tg.arn
  target_id        = aws_instance.k3s_server.id
  port             = 80
}

resource "aws_lb_target_group_attachment" "k3s_agent_attachment" {
  target_group_arn = aws_lb_target_group.aiops_tg.arn
  target_id        = aws_instance.k3s_agent.id
  port             = 80
}

# ==========================================
# Output
# ==========================================
output "alb_dns_name" {
  description = "ALB DNS name"
  value       = aws_lb.aiops_alb.dns_name
}