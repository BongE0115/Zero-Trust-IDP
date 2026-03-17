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

# ==========================================
# Output
# ==========================================
output "rds_endpoint" {
  description = "PostgreSQL RDS endpoint"
  value       = aws_db_instance.aiops_rds.endpoint
}