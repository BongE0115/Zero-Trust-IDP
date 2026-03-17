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

  user_data = templatefile("${path.module}/templates/monitoring.sh.tpl", {
    k3s_server_private_ip = aws_instance.k3s_server.private_ip
    k3s_agent_private_ip  = aws_instance.k3s_agent.private_ip
  })

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
  instance_type          = "t3.micro"
  subnet_id              = aws_subnet.private_a.id
  vpc_security_group_ids = [aws_security_group.k3s_server_sg.id]
  iam_instance_profile   = aws_iam_instance_profile.ssm_profile.name

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
  instance_type          = "t3.micro"
  subnet_id              = aws_subnet.private_b.id
  vpc_security_group_ids = [aws_security_group.k3s_agent_sg.id]
  iam_instance_profile   = aws_iam_instance_profile.ssm_profile.name

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