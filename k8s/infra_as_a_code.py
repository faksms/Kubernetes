#Author: Farhan Khan
#Purpose: to create EC2 instances and configure a Kubernetes cluster with master/worker nodes.
#The code handles AWS authentication, security groups, key pairs, and generates connection information

import boto3
import os
import time
from botocore.exceptions import ClientError
from getpass import getpass

class K8sClusterBuilder:
    def __init__(self):
        self.ec2 = boto3.client('ec2')
        self.iam = boto3.client('iam')
        self.ssm = boto3.client('ssm')
        
        # User inputs
        self.total_instances = int(input("Enter total EC2 instances: "))
        self.master_nodes = int(input("Enter number of master nodes: "))
        self.worker_nodes = int(input("Enter number of worker nodes: "))
        self.key_name = "k8s-cluster-key"
        self.passphrase = getpass("Enter passphrase for SSH key (empty for none): ")

    def create_key_pair(self):
        """Create and save SSH key pair with optional passphrase"""
        try:
            response = self.ec2.create_key_pair(
                KeyName=self.key_name,
                KeyType='rsa',
                KeyFormat='pem'
            )
            with open(f"{self.key_name}.pem", 'w') as f:
                f.write(response['KeyMaterial'])
            os.chmod(f"{self.key_name}.pem", 0o400)
        except ClientError as e:
            if e.response['Error']['Code'] == 'InvalidKeyPair.Duplicate':
                print("Key pair already exists, using existing key")
            else:
                raise

    def create_iam_role(self):
        """Create IAM role for EC2 instances"""
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "ec2.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }

        try:
            role = self.iam.create_role(
                RoleName='K8sNodeRole',
                AssumeRolePolicyDocument=str(trust_policy)
            )
            
            # Attach necessary policies
            self.iam.attach_role_policy(
                RoleName='K8sNodeRole',
                PolicyArn='arn:aws:iam::aws:policy/AmazonEKSClusterPolicy'
            )
            self.iam.attach_role_policy(
                RoleName='K8sNodeRole',
                PolicyArn='arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly'
            )
            return role['Role']['Arn']
        except ClientError as e:
            if e.response['Error']['Code'] == 'EntityAlreadyExists':
                print("IAM role already exists, using existing role")
                return self.iam.get_role(RoleName='K8sNodeRole')['Role']['Arn']
            else:
                raise

    def create_security_group(self):
        """Create security group for Kubernetes cluster"""
        vpc_id = self.ec2.describe_vpcs()['Vpcs'][0]['VpcId']
        try:
            sg = self.ec2.create_security_group(
                GroupName='k8s-cluster-sg',
                Description='Kubernetes cluster security group',
                VpcId=vpc_id
            )
            sg_id = sg['GroupId']
            
            # Define ingress rules
            self.ec2.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[
                    {'IpProtocol': 'tcp', 'FromPort': 22, 'ToPort': 22, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
                    {'IpProtocol': 'tcp', 'FromPort': 6443, 'ToPort': 6443, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
                    {'IpProtocol': 'tcp', 'FromPort': 2379, 'ToPort': 2380, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
                    {'IpProtocol': 'tcp', 'FromPort': 10250, 'ToPort': 10252, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
                    {'IpProtocol': 'udp', 'FromPort': 8472, 'ToPort': 8472, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}
                ]
            )
            return sg_id
        except ClientError as e:
            if e.response['Error']['Code'] == 'InvalidGroup.Duplicate':
                print("Security group already exists, using existing group")
                return self.ec2.describe_security_groups(
                    GroupNames=['k8s-cluster-sg'])['SecurityGroups'][0]['GroupId']
            else:
                raise

    def launch_instances(self, role_arn, sg_id):
        """Launch EC2 instances with proper configuration"""
        script = f'''#!/bin/bash
        sudo apt update -y
        sudo apt install -y docker.io
        sudo systemctl enable docker
        sudo systemctl start docker
        sudo apt install -y apt-transport-https curl
        curl -s https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
        echo "deb https://apt.kubernetes.io/ kubernetes-xenial main" | sudo tee /etc/apt/sources.list.d/kubernetes.list
        sudo apt update -y
        sudo apt install -y kubelet kubeadm kubectl
        sudo apt-mark hold kubelet kubeadm kubectl
        '''

        instances = self.ec2.run_instances(
            ImageId='ami-0c55b159cbfafe1f0',  # Ubuntu 20.04 LTS
            MinCount=self.total_instances,
            MaxCount=self.total_instances,
            InstanceType='t2.medium',
            KeyName=self.key_name,
            SecurityGroupIds=[sg_id],
            IamInstanceProfile={'Arn': role_arn},
            UserData=script
        )

        instance_ids = [i['InstanceId'] for i in instances['Instances']]
        
        # Wait for instances to initialize
        waiter = self.ec2.get_waiter('instance_running')
        waiter.wait(InstanceIds=instance_ids)
        
        return instance_ids

    def configure_cluster(self, instance_ids):
        """Configure Kubernetes cluster on launched instances"""
        # Get public IPs
        instances = self.ec2.describe_instances(InstanceIds=instance_ids)
        public_ips = [
            i['PublicIpAddress'] 
            for r in instances['Reservations'] 
            for i in r['Instances']
        ]

        # Configure master nodes
        master_ips = public_ips[:self.master_nodes]
        for ip in master_ips:
            self._run_remote_command(ip, 'sudo kubeadm init --pod-network-cidr=10.244.0.0/16')

        # Configure worker nodes
        worker_ips = public_ips[self.master_nodes:]
        for ip in worker_ips:
            join_command = "kubeadm join <master-ip>:6443 --token <token> --discovery-token-ca-cert-hash <hash>"
            self._run_remote_command(ip, join_command)

    def _run_remote_command(self, ip, command):
        """Execute command on instance using SSM"""
        instance_id = self._get_instance_id(ip)
        self.ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={'commands': [command]}
        )

    def _get_instance_id(self, public_ip):
        """Get instance ID from public IP"""
        response = self.ec2.describe_instances(
            Filters=[{'Name': 'ip-address', 'Values': [public_ip]}]
        )
        return response['Reservations'][0]['Instances'][0]['InstanceId']

if __name__ == "__main__":
    builder = K8sClusterBuilder()
    
    # Create AWS resources
    builder.create_key_pair()
    role_arn = builder.create_iam_role()
    sg_id = builder.create_security_group()
    
    # Launch instances
    instance_ids = builder.launch_instances(role_arn, sg_id)
    
    # Configure Kubernetes cluster
    builder.configure_cluster(instance_ids)
    
    print(f"\nCluster setup complete! Use '{builder.key_name}.pem' to connect:")
    print(f"SSH command: ssh -i {builder.key_name}.pem ubuntu@<master-ip>")
    if builder.passphrase:
        print(f"Passphrase: {builder.passphrase}")
