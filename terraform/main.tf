# ==================================================
# --------------------------------------------------
# 1. 네트워크 인프라 (VPC,Subnet,IGW,RT)
# --------------------------------------------------
# ==================================================

provider "aws" {
  region = "ap-northeast-2"
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
}

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

# ==================================================
# --------------------------------------------------
# 2. 보안 및 권한 (IAM,Security group)
# --------------------------------------------------
# ==================================================

# ==========================================
# IAM Role for EC2 SSM Access
# ==========================================
resource "aws_iam_role" "ssm_role" {
  name = "aiops-ssm-role"

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


# ==========================================
# Attach SSM Managed Policy
# ==========================================
resource "aws_iam_role_policy_attachment" "ssm_attach" {
  role       = aws_iam_role.ssm_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# ==========================================
# EC2 Instance Profile
# ==========================================
resource "aws_iam_instance_profile" "ssm_profile" {
  name = "aiops-ssm-profile"
  role = aws_iam_role.ssm_role.name
}

# ===========================================
# ssh 키 페어 생성
# =========================================== 

# 1. RSA 알고리즘을 사용한 개인키 생성
resource "tls_private_key" "aiops_key" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

# 2. AWS에 공용키(Public Key) 등록
resource "aws_key_pair" "generated_key" {
  key_name   = var.ssh_key_name
  public_key = tls_private_key.aiops_key.public_key_openssh
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

  ingress {
  description = "SSH from Admin IP"
  from_port   = 22
  to_port     = 22
  protocol    = "tcp"
  cidr_blocks = var.admin_cidr # 관리자님의 공인 IP에서만 접속 허용 
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

  # 수정된 aiops-nat-sg 부분
  ingress {
    description = "Allow all from private subnets"
    from_port   = 0
    to_port     = 0
    protocol    = "-1" # 모든 프로토콜 허용
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

  ingress {
    description     = "K3s API from monitoring node"
    from_port       = 6443
    to_port         = 6443
    protocol        = "tcp"
    security_groups = [aws_security_group.monitoring_sg.id]
  }

  ingress {
    description     = "Kubelet metrics from monitoring node"
    from_port       = 10250
    to_port         = 10250
    protocol        = "tcp"
    security_groups = [aws_security_group.monitoring_sg.id]
  }

  ingress {
    description = "Flannel VXLAN self"
    from_port   = 8472
    to_port     = 8472
    protocol    = "udp"
    self        = true
  }

  ingress {
    description     = "HTTP from ALB"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  ingress {
  description     = "SSH from Monitoring Node (Ansible)"
  from_port       = 22
  to_port         = 22
  protocol        = "tcp"
  security_groups = [aws_security_group.monitoring_sg.id] # 모니터링 SG를 소스로 지정 
  }

  ingress {
    description = "ICMP from VPC for testing"
    from_port   = -1
    to_port     = -1
    protocol    = "icmp"
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

  ingress {
    description     = "Kubelet metrics from monitoring node"
    from_port       = 10250
    to_port         = 10250
    protocol        = "tcp"
    security_groups = [aws_security_group.monitoring_sg.id]
  }

  ingress {
    description = "Flannel VXLAN self"
    from_port   = 8472
    to_port     = 8472
    protocol    = "udp"
    self        = true
  }

  ingress {
    description     = "HTTP from ALB"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  ingress {
  description     = "SSH from Monitoring Node (Ansible)"
  from_port       = 22
  to_port         = 22
  protocol        = "tcp"
  security_groups = [aws_security_group.monitoring_sg.id] # 모니터링 SG를 소스로 지정 
  }

  ingress {
    description = "ICMP from VPC for testing"
    from_port   = -1
    to_port     = -1
    protocol    = "icmp"
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


# Master receives K3s API from workers
resource "aws_security_group_rule" "k3s_server_api_from_agent" {
  type                     = "ingress"
  from_port                = 6443
  to_port                  = 6443
  protocol                 = "tcp"
  security_group_id        = aws_security_group.k3s_server_sg.id
  source_security_group_id = aws_security_group.k3s_agent_sg.id
  description              = "K3s API from worker nodes"
}

# Master receives Flannel from workers
resource "aws_security_group_rule" "k3s_server_flannel_from_agent" {
  type                     = "ingress"
  from_port                = 8472
  to_port                  = 8472
  protocol                 = "udp"
  security_group_id        = aws_security_group.k3s_server_sg.id
  source_security_group_id = aws_security_group.k3s_agent_sg.id
  description              = "Flannel VXLAN from worker nodes"
}

# Worker receives Flannel from master
resource "aws_security_group_rule" "k3s_agent_flannel_from_server" {
  type                     = "ingress"
  from_port                = 8472
  to_port                  = 8472
  protocol                 = "udp"
  security_group_id        = aws_security_group.k3s_agent_sg.id
  source_security_group_id = aws_security_group.k3s_server_sg.id
  description              = "Flannel VXLAN from master"
}

# ALB에서 K3s 노드(Master/Worker)의 NodePort로 가는 트래픽 허용
resource "aws_security_group_rule" "allow_alb_to_nodeport_master" {
  type                     = "ingress"
  from_port                = 30080
  to_port                  = 30080
  protocol                 = "tcp"
  security_group_id        = aws_security_group.k3s_server_sg.id
  source_security_group_id = aws_security_group.alb_sg.id
}

resource "aws_security_group_rule" "allow_alb_to_nodeport_worker" {
  type                     = "ingress"
  from_port                = 30080
  to_port                  = 30080
  protocol                 = "tcp"
  security_group_id        = aws_security_group.k3s_agent_sg.id
  source_security_group_id = aws_security_group.alb_sg.id
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
  port             = 30080
}

resource "aws_lb_target_group_attachment" "k3s_agent_attachment" {
  target_group_arn = aws_lb_target_group.aiops_tg.arn
  target_id        = aws_instance.k3s_agent.id
  port             = 30080
}



# ==================================================
# --------------------------------------------------
# 4. 데이터 베이스 (RDS)
# --------------------------------------------------
# ==================================================

# ==========================================
# RDS Security Group
# ==========================================
resource "aws_security_group" "rds_sg" {
  name        = "aiops-rds-sg"
  description = "Security group for AIOps RDS PostgreSQL"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Allow PostgreSQL traffic from K3s master"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.k3s_server_sg.id]
  }

  ingress {
    description     = "Allow PostgreSQL traffic from K3s worker"
    from_port       = 5432
    to_port         = 5432
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
# RDS Subnet Group
# ==========================================
resource "aws_db_subnet_group" "rds_subnet_group" {
  name       = "aiops-rds-subnet-group"
  subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id]

  tags = {
    Name = "aiops-rds-subnet-group"
  }
}

# ==========================================
# PostgreSQL RDS Instance
# ==========================================
resource "aws_db_instance" "aiops_rds" {
  identifier = "aiops-postgres-db"

  engine         = "postgres"
  engine_version = "15"

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
    Name      = "aiops-rds-postgres"
    Project   = "AIOps"
    ManagedBy = "Terraform"
  }
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
  iam_instance_profile        = aws_iam_instance_profile.ssm_profile.name
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
    content      = templatefile("${path.module}/templates/monitoring.sh.tpl", {
      k3s_server_private_ip = aws_instance.k3s_server.private_ip
      k3s_agent_private_ip  = aws_instance.k3s_agent.private_ip
      k3s_token             = var.k3s_token
      ssh_private_key       = tls_private_key.aiops_key.private_key_pem
      
      ansible_playbook_content = templatefile("${path.module}/templates/setup_k3s.yml.tpl", {
        k3s_token    = var.k3s_token
        rds_endpoint = aws_db_instance.aiops_rds.address
      })

      argocd_app_content           = templatefile("${path.module}/../argo-apps/argocd-app.yml.tpl", {})
      forensic_sandbox_app_content = templatefile("${path.module}/../argo-apps/forensic-sandbox-app.yml.tpl", {})
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
  iam_instance_profile        = aws_iam_instance_profile.ssm_profile.name
  associate_public_ip_address = true

  # 위에서 만든 압축 monitoring_config를 가져와서 넣어준다. 
  user_data_base64 = data.cloudinit_config.monitoring_config.rendered

  tags = {
    Name = "aiops-monitoring-control"
    Role = "Monitoring_And_Ansible_Control_Node"
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
  iam_instance_profile   = aws_iam_instance_profile.ssm_profile.name

  key_name               = aws_key_pair.generated_key.key_name

  root_block_device {
    volume_size = 30  # 기본 8GB에서 30GB로 증설
    volume_type = "gp3" # 최신 고성능 범용 스토리지
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/templates/k3s_server.sh.tpl", {
    tailscale_auth_key = var.tailscale_auth_key
    k3s_token          = var.k3s_token
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
  iam_instance_profile   = aws_iam_instance_profile.ssm_profile.name

  key_name               = aws_key_pair.generated_key.key_name

  root_block_device {
    volume_size = 30  # 기본 8GB에서 30GB로 증설
    volume_type = "gp3" # 최신 고성능 범용 스토리지
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

