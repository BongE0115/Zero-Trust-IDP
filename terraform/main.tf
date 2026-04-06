# ==================================================
# --------------------------------------------------
# 1. 네트워크 인프라 (VPC,Subnet,IGW,RT)
# --------------------------------------------------
# ==================================================

# tfstate 파일 S3에 저장 및 DynamoDB를 통한 동시 apply 방지 
terraform {
  backend "s3" {
    bucket         = "my-team-zerotrust-tfstate-1234"
    key            = "terraform.tfstate"
    region         = "ap-northeast-2"
    dynamodb_table = "terraform-state-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = "ap-northeast-2"
}

# 현재 AWS 계정 정보 및 리전 정보 가져오는 데이터 소스
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
# =======================================

# EC2 인스턴스에 사용할 Ubuntu 이미지 
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
}
# ======================================

# ==========================================
# 1. VPC
# ==========================================
resource "aws_vpc" "main" {
  cidr_block           = "10.10.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name      = "aiops-vpc"
    Project   = "AIOps"
    ManagedBy = "Terraform"
  }
}

# ==========================================
# 2. Public Subnets
# ==========================================
resource "aws_subnet" "public_a" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.10.1.0/24"
  availability_zone       = "ap-northeast-2a"
  map_public_ip_on_launch = true

  tags = {
    Name = "aiops-public-subnet-a"
  }
}

resource "aws_subnet" "public_b" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.10.2.0/24"
  availability_zone       = "ap-northeast-2b"
  map_public_ip_on_launch = true

  tags = {
    Name = "aiops-public-subnet-b"
  }
}

# ==========================================
# 3. Private Subnets
# ==========================================
resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.10.10.0/24"
  availability_zone = "ap-northeast-2a"

  tags = {
    Name = "aiops-private-subnet-a"
  }
}

resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.10.20.0/24"
  availability_zone = "ap-northeast-2b"

  tags = {
    Name = "aiops-private-subnet-b"
  }
}

# ==========================================
# 4. Internet Gateway
# ==========================================
resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "aiops-igw"
  }
}

# ==========================================
# 5. Route Tables
# ==========================================
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }

  tags = {
    Name = "aiops-public-rt"
  }
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "public_b" {
  subnet_id      = aws_subnet.public_b.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block           = "0.0.0.0/0"
    network_interface_id = aws_instance.nat.primary_network_interface_id
  }

  tags = {
    Name = "aiops-private-rt"
  }
}

resource "aws_route_table_association" "private_a" {
  subnet_id      = aws_subnet.private_a.id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table_association" "private_b" {
  subnet_id      = aws_subnet.private_b.id
  route_table_id = aws_route_table.private.id
}

resource "aws_route53_zone" "private_internal" {
  name = "example.internal"
  vpc {
    vpc_id = aws_vpc.main.id
  }
}

# ==================================================
# --------------------------------------------------
# 2. 보안 및 권한 (IAM,Security group)
# --------------------------------------------------
# ==================================================

# ==========================================
# [SET 1] IAM Role for K3s nodes (master / worker)
# - SSM managed-node permissions
# - GitHub dispatch token SSM read permissions
# ==========================================

# 1. 역할(Role)
resource "aws_iam_role" "ssm_node_role" {
  name = "aiops-ssm-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

# 2-1. 정책(Policy) 연결: AWS SSM으로 접속 가능 
resource "aws_iam_role_policy_attachment" "ssm_node_attach" {
  role       = aws_iam_role.ssm_node_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# 2-2. 정책(Policy) 추가: GitHub Dispatch 토큰 읽기 권한 -> 깃 액션 워크플로우 원격 실행 트리거
resource "aws_iam_role_policy" "ssm_node_github_dispatch_ssm_policy" {
  name = "aiops-ssm-node-github-dispatch-ssm-policy"
  role = aws_iam_role.ssm_node_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadGithubDispatchTokenFromSSM"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter"
        ]
        Resource = "arn:aws:ssm:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:parameter/zero-trust-idp/github-dispatch-token"
      },
      {
        Sid    = "DecryptGithubDispatchTokenWithAwsManagedKms"
        Effect = "Allow"
        Action = [
          "kms:Decrypt"
        ]
        Resource = "arn:aws:kms:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"
      }
    ]
  })
}

# 3. 붙이기(Instance Profile): EC2에 역할을 부여하기 위한 프로필
resource "aws_iam_instance_profile" "ssm_node_profile" {
  name = "aiops-ssm-node-profile"
  role = aws_iam_role.ssm_node_role.name
}


# ==========================================
# [SET 2] IAM Role for Monitoring node
# - SSM managed-node permissions
# - SSM Run Command operator permissions (for K3s_Server)
# - GitHub Runner bootstrap token SSM read permissions
# ==========================================

# 1. 역할(Role)
resource "aws_iam_role" "ssm_monitoring_role" {
  name = "aiops-ssm-monitoring-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

# 2-1. 정책(Policy) 연결: AWS SSM으로 접속 가능
resource "aws_iam_role_policy_attachment" "ssm_monitoring_attach" {
  role       = aws_iam_role.ssm_monitoring_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# 2-2. 정책(Policy) 추가: 모니터링 서버가 K3s 마스터 노드에 SSM으로 명령 내릴 수 있는 권한
resource "aws_iam_role_policy" "monitoring_ssm_operator_policy" {
  name = "aiops-monitoring-ssm-operator-policy"
  role = aws_iam_role.ssm_monitoring_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # AWS-RunShellScript 같은 SSM 문서를 사용할 수 있도록 허용
      {
        Sid    = "AllowRunCommandWithAwsDocuments"
        Effect = "Allow"
        Action = [
          "ssm:SendCommand"
        ]
        Resource = [
          "arn:aws:ssm:*:*:document/AWS-RunShellScript",
          "arn:aws:ssm:*:*:document/AWS-*"
        ]
      },
      # Role=K3s_Server 태그가 붙은 EC2 인스턴스에만 명령 허용
      {
        Sid    = "AllowRunCommandToTaggedMasterOnly"
        Effect = "Allow"
        Action = [
          "ssm:SendCommand"
        ]
        Resource = "arn:aws:ec2:*:*:instance/*"
        Condition = {
          StringLike = {
            "ssm:resourceTag/Role" = "K3s_Server"
          }
        }
      },
      # 명령 결과 조회 및 대상 탐색
      {
        Sid    = "AllowCommandReadOps"
        Effect = "Allow"
        Action = [
          "ssm:GetCommandInvocation",
          "ssm:ListCommandInvocations",
          "ssm:ListCommands",
          "ssm:DescribeInstanceInformation",
          "ec2:DescribeInstances"
        ]
        Resource = "*"
      }
    ]
  })
}

# 2-3. 정책(Policy) 추가: 모니터링 서버를 깃 러너로 만들기 위해 AWS 파라미터 스토어에 저장된 깃 허브 Bootstrape 토큰을 읽을 수 있는 권한 부 
resource "aws_iam_role_policy" "monitoring_runner_bootstrap_ssm_policy" {
  name = "aiops-monitoring-runner-bootstrap-ssm-policy"
  role = aws_iam_role.ssm_monitoring_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadGithubRunnerBootstrapTokenFromSSM"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter"
        ]
        Resource = "arn:aws:ssm:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:parameter${var.github_runner_token_ssm_parameter_name}"
      },
      {
        Sid    = "DecryptGithubRunnerBootstrapTokenWithAwsManagedKms"
        Effect = "Allow"
        Action = [
          "kms:Decrypt"
        ]
        Resource = "arn:aws:kms:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"
      }
    ]
  })
}

# 3. 붙이기(Instance Profile): EC2에 역할을 부여하기 위한 프로필
resource "aws_iam_instance_profile" "ssm_monitoring_profile" {
  name = "aiops-ssm-monitoring-profile"
  role = aws_iam_role.ssm_monitoring_role.name
}



# ==========================================
# 1. Monitoring Control SG
# ==========================================
resource "aws_security_group" "monitoring_sg" {
  name        = "aiops-monitoring-sg"
  description = "Security group for Monitoring + Ansible control node"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "Grafana from Admin IP"
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = var.admin_cidr
  }

  ingress {
    description = "Prometheus UI from Admin IP"
    from_port   = 9090
    to_port     = 9090
    protocol    = "tcp"
    cidr_blocks = var.admin_cidr
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "aiops-monitoring-sg"
  }
}

# ==========================================
# 2. ALB SG
# ==========================================
resource "aws_security_group" "alb_sg" {
  name        = "aiops-alb-sg"
  description = "Allow HTTP traffic from internet to ALB"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP from Internet"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS (ArgoCD) from Internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Frontend 8080 from Internet"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "aiops-alb-sg"
  }
}

# ==========================================
# 3. NAT SG
# ==========================================
resource "aws_security_group" "nat_sg" {
  name        = "aiops-nat-sg"
  description = "NAT instance SG for private subnet outbound"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "Allow all from private subnets"
    from_port   = 0
    to_port     = 0
    protocol    = "-1" 
    cidr_blocks = [aws_subnet.private_a.cidr_block, aws_subnet.private_b.cidr_block]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "aiops-nat-sg"
  }
}

# ==========================================
# 4. K3s Master SG
# ==========================================
resource "aws_security_group" "k3s_server_sg" {
  name        = "aiops-k3s-server-sg"
  description = "Security group for K3s master node"
  vpc_id      = aws_vpc.main.id

  # 🔥 수정: Tailscale 망(100.64.0.0/10)도 K3s API 접속 허용
  ingress {
    description = "K3s API from VPC and Tailscale"
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.main.cidr_block, "100.64.0.0/10"]
  }

  # 🔥 수정: Tailscale 망도 Kubelet 통신 허용
  ingress {
    description = "Kubelet metrics from VPC and Tailscale"
    from_port   = 10250
    to_port     = 10250
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.main.cidr_block, "100.64.0.0/10"]
  }

  ingress {
    description = "Node Exporter metrics"
    from_port   = 9100
    to_port     = 9100
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.main.cidr_block, "100.64.0.0/10"]
  }

  # 🔥 수정: Tailscale 노드도 Flannel 가상 네트워크에 참여 허용
  ingress {
    description = "Flannel VXLAN from VPC and Tailscale"
    from_port   = 8472
    to_port     = 8472
    protocol    = "udp"
    cidr_blocks = [aws_vpc.main.cidr_block, "100.64.0.0/10"]
  }

  # 🔥 핵심 추가: Tailscale 직접 통신(P2P)을 위한 전용 포트 개방
  ingress {
    description = "Tailscale P2P Direct Connection"
    from_port   = 41641
    to_port     = 41641
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP from ALB"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.main.cidr_block]
  }

  ingress {
    description     = "NodePort from ALB"
    from_port       = 30080
    to_port         = 30082
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  ingress {
    description     = "ICMP from VPC for testing"
    from_port       = -1
    to_port         = -1
    protocol        = "icmp"
    security_groups = [aws_security_group.monitoring_sg.id]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "aiops-k3s-server-sg"
  }
}

# ==========================================
# 5. K3s Worker SG
# ==========================================
resource "aws_security_group" "k3s_agent_sg" {
  name        = "aiops-k3s-agent-sg"
  description = "Security group for K3s worker node"
  vpc_id      = aws_vpc.main.id

  # 🔥 수정: Tailscale 망도 Kubelet 통신 허용
  ingress {
    description = "Kubelet metrics from VPC and Tailscale"
    from_port   = 10250
    to_port     = 10250
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.main.cidr_block, "100.64.0.0/10"]
  }

  ingress {
    description = "Kafka Broker from Tailscale"
    from_port   = 9092
    to_port     = 9092
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.main.cidr_block,"100.64.0.0/10"] # Tailscale 망 전체 허용
  }

  ingress {
    description     = "Node Exporter metrics"
    from_port       = 9100
    to_port         = 9100
    protocol        = "tcp"
    security_groups = [aws_security_group.monitoring_sg.id]
  }

  # 🔥 수정: Tailscale 노드도 Flannel 가상 네트워크에 참여 허용
  ingress {
    description = "Flannel VXLAN from VPC and Tailscale"
    from_port   = 8472
    to_port     = 8472
    protocol    = "udp"
    cidr_blocks = [aws_vpc.main.cidr_block, "100.64.0.0/10"]
  }

  # 🔥 핵심 추가: Tailscale 직접 통신(P2P)을 위한 전용 포트 개방
  ingress {
    description = "Tailscale P2P Direct Connection"
    from_port   = 41641
    to_port     = 41641
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description     = "HTTP from ALB"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  ingress {
    description     = "NodePort from ALB"
    from_port       = 30080
    to_port         = 30082
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  ingress {
    description     = "ICMP from VPC for testing"
    from_port       = -1
    to_port         = -1
    protocol        = "icmp"
    security_groups = [aws_security_group.monitoring_sg.id]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "aiops-k3s-agent-sg"
  }
}




# ==================================================
# --------------------------------------------------
# 3. 로드 밸런스 (ALB)
# --------------------------------------------------
# ==================================================

# ==========================================
# ALB
# ==========================================
resource "aws_lb" "aiops_alb" {
  name                       = "aiops-alb"
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb_sg.id]
  subnets                    = [aws_subnet.public_a.id, aws_subnet.public_b.id]
  enable_deletion_protection = false # terraform destroy 하기 위해 false로 설정

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
  port     = 30080
  protocol = "HTTP"
  vpc_id   = aws_vpc.main.id

  health_check {
    interval            = 30
    path                = "/healthz" # ArgoCD 전용 건강 검진 경로
    port                = "30080"
    protocol            = "HTTP"
    timeout             = 5
    healthy_threshold   = 3
    unhealthy_threshold = 3
    matcher             = "200-399"
  }

  tags = {
    Name      = "aiops-tg"
    Project   = "AIOps"
    ManagedBy = "Terraform"
  }
}

resource "aws_lb_target_group" "boutique_frontend_tg" {
  name     = "boutique-frontend-tg"
  port     = 30081
  protocol = "HTTP"
  vpc_id   = aws_vpc.main.id

  # 🚨 헬스 체크를 명시해야 ALB가 노드를 Healthy로 인식합니다.
  health_check {
    path                = "/" # 프론트엔드 메인 페이지 혹은 /healthz
    port                = "30081"
    protocol            = "HTTP"
    healthy_threshold   = 3
    unhealthy_threshold = 3
    matcher             = "200-399"
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

resource "aws_lb_listener" "frontend_8080" {
  load_balancer_arn = aws_lb.aiops_alb.arn
  port              = "8080"
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.boutique_frontend_tg.arn
  }
}

# ==========================================
# Target Attachments
# ==========================================
resource "aws_lb_target_group_attachment" "k3s_server_attachment" {
  target_group_arn = aws_lb_target_group.aiops_tg.arn
  target_id        = aws_instance.k3s_server.id
  port             = 30080
}

resource "aws_lb_target_group_attachment" "k3s_agent_attachment" {
  target_group_arn = aws_lb_target_group.aiops_tg.arn
  target_id        = aws_instance.k3s_agent.id
  port             = 30080
}

resource "aws_lb_target_group_attachment" "frontend_attachment" {
  target_group_arn = aws_lb_target_group.boutique_frontend_tg.arn
  target_id        = aws_instance.k3s_agent.id
  port             = 30081
}

# ==================================================
# 4. 데이터 베이스 (RDS - MySQL)
# ==================================================

# ==========================================
# 4.1 RDS Security Group (MySQL 3306)
# ==========================================
resource "aws_security_group" "rds_sg" {
  name        = "aiops-rds-sg"
  description = "Security group for AIOps RDS MySQL"
  vpc_id      = aws_vpc.main.id

  # K3s Master로부터의 접속 허용
  ingress {
    description     = "Allow MySQL traffic from K3s master"
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.k3s_server_sg.id]
  }

  # K3s Worker로부터의 접속 허용
  ingress {
    description     = "Allow MySQL traffic from K3s worker"
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.k3s_agent_sg.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "aiops-rds-sg"
  }
}

# ==========================================
# 4.2 RDS Subnet Group
# ==========================================
resource "aws_db_subnet_group" "rds_subnet_group" {
  name       = "aiops-rds-subnet-group"
  subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id]

  tags = {
    Name = "aiops-rds-subnet-group"
  }
}

# ==========================================
# 4.3 MySQL RDS Instance
# ==========================================
resource "aws_db_instance" "aiops_rds" {
  identifier = "aiops-mysql-db"

  engine         = "mysql"
  engine_version = "8.0" # MySQL 8.0 시리즈 사용
  port           = 3306

  instance_class    = "db.t3.micro"
  allocated_storage = 20
  storage_type      = "gp2"

  db_name  = "aiopsdb"
  username = var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.rds_subnet_group.name
  vpc_security_group_ids = [aws_security_group.rds_sg.id]

  publicly_accessible = false
  skip_final_snapshot = true

  tags = {
    Name      = "aiops-rds-mysql"
    Project   = "AIOps"
    ManagedBy = "Terraform"
  }
}

# ==========================================
# 4.4 Internal DNS Record (Route53)
# ==========================================
# 기존에 생성된 aws_route53_zone.private_internal이 있다면 중복 선언하지 않아도 됩니다.
resource "aws_route53_record" "rds_cname" {
  zone_id = aws_route53_zone.private_internal.zone_id
  name    = "rds.${var.private_dns_zone_name}"
  type    = "CNAME"
  ttl     = 60
  records = [aws_db_instance.aiops_rds.address]
}

# ==================================================
# --------------------------------------------------
# 5. 컴퓨팅 (EC2)
# --------------------------------------------------
# ==================================================


# ==========================================
# NAT Instance
# ==========================================
resource "aws_instance" "nat" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = "t3.micro"
  subnet_id                   = aws_subnet.public_a.id
  vpc_security_group_ids      = [aws_security_group.nat_sg.id]
  iam_instance_profile        = aws_iam_instance_profile.ssm_node_profile.name
  associate_public_ip_address = true
  source_dest_check           = false

  user_data = <<-EOF
              #!/bin/bash
              set -eux

              sysctl -w net.ipv4.ip_forward=1
              sed -i 's/#net.ipv4.ip_forward=1/net.ipv4.ip_forward=1/' /etc/sysctl.conf || true
              echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf

              IFACE=$(ip -o -4 route show to default | awk '{print $5}')
              iptables -t nat -A POSTROUTING -o $${IFACE} -j MASQUERADE

              apt-get update -y
              DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent
              netfilter-persistent save
              EOF

  tags = {
    Name = "aiops-nat-instance"
  }
}

# =================================================================
# 1. 모니터링 서버에 넣을 압축된 User Data 생성기
# =================================================================
data "cloudinit_config" "monitoring_config" {
  gzip          = true
  base64_encode = true

  part {
    content_type = "text/x-shellscript"
    content = templatefile("${path.module}/templates/monitoring.sh.tpl", {
      aws_region            = "ap-northeast-2"
      k3s_server_private_ip = aws_instance.k3s_server.private_ip
      k3s_agent_private_ip  = aws_instance.k3s_agent.private_ip

      gitops_repo_url        = "https://github.com/BongE0115/Zero-Trust-IDP.git"
      gitops_target_revision = "jy"

      argocd_values_content = file("${path.module}/../gitops/bootstrap/argocd/values.yaml")

      enable_monitoring_github_runner      = var.enable_monitoring_github_runner
      github_runner_scope                  = var.github_runner_scope
      github_runner_owner                  = var.github_runner_owner
      github_runner_repository             = var.github_runner_repository
      github_runner_labels_csv             = join(",", var.github_runner_labels)
      github_runner_version                = var.github_runner_version
      github_runner_token_ssm_parameter    = var.github_runner_token_ssm_parameter_name

      tailscale_auth_key = var.tailscale_auth_key
    })
  }
}

# ==========================================
# Monitoring + Ansible Control Node
# ==========================================
resource "aws_instance" "monitoring_server" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = "t3.micro"
  subnet_id                   = aws_subnet.public_a.id
  vpc_security_group_ids      = [aws_security_group.monitoring_sg.id]
  iam_instance_profile        = aws_iam_instance_profile.ssm_monitoring_profile.name
  associate_public_ip_address = true

  user_data_base64            = data.cloudinit_config.monitoring_config.rendered
  user_data_replace_on_change = true

  tags = {
    Name          = "aiops-monitoring-control"
    Role          = "Monitoring_Node"
    GithubRunner  = var.enable_monitoring_github_runner ? "enabled" : "disabled"
  }
}

# ==========================================
# K3s Master
# ==========================================
resource "aws_instance" "k3s_server" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = "m7i-flex.large"
  subnet_id              = aws_subnet.private_a.id
  vpc_security_group_ids = [aws_security_group.k3s_server_sg.id]
  iam_instance_profile   = aws_iam_instance_profile.ssm_node_profile.name

  root_block_device {
    volume_size           = 30    # 기본 8GB에서 30GB로 증설
    volume_type           = "gp3" # 최신 고성능 범용 스토리지
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/templates/k3s_server.sh.tpl", {
    tailscale_auth_key = var.tailscale_auth_key
    k3s_token          = var.k3s_token
    local_tailscale_ip = var.local_tailscale_ip
    frontend_addr      = "${aws_lb.aiops_alb.dns_name}:8080"
    project_name       = "Zero-Trust-IDP"
    slack_bot_token    = var.slack_bot_token
    slack_channel      = var.slack_channel
  })

  tags = {
    Name = "aiops-k3s-server-aza"
    Role = "K3s_Server"
  }
}

# ==========================================
# K3s Worker
# ==========================================
resource "aws_instance" "k3s_agent" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = "c7i-flex.large"
  subnet_id              = aws_subnet.private_b.id
  vpc_security_group_ids = [aws_security_group.k3s_agent_sg.id]
  iam_instance_profile   = aws_iam_instance_profile.ssm_node_profile.name

  root_block_device {
    volume_size           = 30    # 기본 8GB에서 30GB로 증설
    volume_type           = "gp3" # 최신 고성능 범용 스토리지
    delete_on_termination = true
  }


  user_data = templatefile("${path.module}/templates/k3s_agent.sh.tpl", {
    tailscale_auth_key = var.tailscale_auth_key
    k3s_token          = var.k3s_token
    k3s_server_ip      = aws_instance.k3s_server.private_ip
  })

  tags = {
    Name = "aiops-k3s-agent-azb"
    Role = "K3s_Agent"
  }
}


# ==========================================
# [추가] Slack Interactivity 수신용 Target Group (터미널 4 app.py 용)
# ==========================================
resource "aws_lb_target_group" "slack_receiver_tg" {
  name     = "aiops-slack-receiver-tg"
  port     = 30082 # K3s NodePort (임의 지정, app.py 서비스용)
  protocol = "HTTP"
  vpc_id   = aws_vpc.main.id

  health_check {
    path                = "/health" # app.py에 헬스체크용 엔드포인트가 하나 있어야 합니다.
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 3
    unhealthy_threshold = 3
    matcher             = "200-399"
  }
}

# Target Group에 K3s 노드 연결
resource "aws_lb_target_group_attachment" "slack_receiver_server_attach" {
  target_group_arn = aws_lb_target_group.slack_receiver_tg.arn
  target_id        = aws_instance.k3s_server.id
  port             = 30082
}

resource "aws_lb_target_group_attachment" "slack_receiver_agent_attach" {
  target_group_arn = aws_lb_target_group.slack_receiver_tg.arn
  target_id        = aws_instance.k3s_agent.id
  port             = 30082
}

# ==========================================
# [추가] ALB Listener Rule (경로 기반 라우팅)
# - /slack/actions 로 들어오는 요청을 app.py로 보냅니다.
# ==========================================
resource "aws_lb_listener_rule" "slack_action_rule" {
  listener_arn = aws_lb_listener.http.arn # 기존 80번 리스너에 룰 추가
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.slack_receiver_tg.arn
  }

  condition {
    path_pattern {
      values = ["/slack/actions*"]
    }
  }
}


# 1. CloudFront 배포 정의
resource "aws_cloudfront_distribution" "aiops_cdn" {
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "AIOps 프로젝트 통합 HTTPS 대문"
  
  # [원본 1] AIOps 백엔드 (80포트)
  origin {
    domain_name = aws_lb.aiops_alb.dns_name 
    origin_id   = "Origin-AIOps-80"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # [원본 2] Boutique 쇼핑몰 (8080포트)
  origin {
    domain_name = aws_lb.aiops_alb.dns_name
    origin_id   = "Origin-Boutique-8080"

    custom_origin_config {
      http_port              = 8080
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # -----------------------------------------------------------
  # 🚨 [규칙 1] 슬랙 전용 (80포트로 배달)
  # -----------------------------------------------------------
  ordered_cache_behavior {
    path_pattern     = "/slack/*"
    target_origin_id = "Origin-AIOps-80"

    allowed_methods  = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods   = ["GET", "HEAD"]
    
    viewer_protocol_policy = "redirect-to-https"
    
    # 캐시 끄기 (실시간 통신 필수)
    cache_policy_id = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # CachingDisabled (AWS 고정 ID)
  }

  # -----------------------------------------------------------
  # [기본 규칙] 나머지 모든 접속 (8080 쇼핑몰로 배달)
  # -----------------------------------------------------------
  default_cache_behavior {
    target_origin_id = "Origin-Boutique-8080"

    allowed_methods  = ["GET", "HEAD"]
    cached_methods   = ["GET", "HEAD"]

    viewer_protocol_policy = "redirect-to-https"
    min_ttl                = 0
    default_ttl            = 3600
    max_ttl                = 86400

    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = true # 도메인 없어도 공짜 HTTPS 주소 사용
  }
}

# 2. 생성된 주소를 터미널에 출력 (슬랙에 복붙용)
output "cloudfront_url" {
  value = aws_cloudfront_distribution.aiops_cdn.domain_name
}