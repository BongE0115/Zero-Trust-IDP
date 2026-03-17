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