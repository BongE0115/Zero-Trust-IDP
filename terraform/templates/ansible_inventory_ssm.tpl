[k3s_server]
master ansible_host=${k3s_server_id} ansible_connection=amazon.aws.aws_ssm ansible_aws_ssm_region=${aws_region} ansible_aws_ssm_bucket_name=${ssm_bucket_name}

[k3s_agent]
worker ansible_host=${k3s_agent_id} ansible_connection=amazon.aws.aws_ssm ansible_aws_ssm_region=${aws_region} ansible_aws_ssm_bucket_name=${ssm_bucket_name}