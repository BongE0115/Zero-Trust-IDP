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
    cidr_blocks = [var.admin_cidr]
  }

  ingress {
    description = "Prometheus UI from Admin IP"
    from_port   = 9090
    to_port     = 9090
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
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

  ingress {
    description = "HTTP from private subnets"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [aws_subnet.private_a.cidr_block, aws_subnet.private_b.cidr_block]
  }

  ingress {
    description = "HTTPS from private subnets"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
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
    description = "ICMP from VPC for testing"
    from_port   = -1
    to_port     = -1
    protocol    = "icmp"
    cidr_blocks = [aws_vpc.main.cidr_block]
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
    description = "ICMP from VPC for testing"
    from_port   = -1
    to_port     = -1
    protocol    = "icmp"
    cidr_blocks = [aws_vpc.main.cidr_block]
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