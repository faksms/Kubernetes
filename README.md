# Setup Your K8s Cluster with AWS EC2 
![image](https://github.com/user-attachments/assets/8b600410-6e9a-4290-ae44-4cd409ba2b1b)


## Docker & Kubernetes Installation Script

Below steps are the installation of Docker and Kubernetes components, including `cri-dockerd`. It ensures that necessary dependencies are installed and services are properly configured.

## High Level Steps

- Installs Docker and sets up its repository
- Installs `cri-dockerd` and configures it as a system service
- Installs Kubernetes components (`kubeadm`, `kubelet`, `kubectl`)
- Enables and verifies services

## Prerequisites

- CreateTwo EC2 Instances ( 1 Master and 1 Worker)
  ![image](https://github.com/user-attachments/assets/a737ab20-d801-4e2f-8087-8d817da684be)
- Create a new security group as shown below. We need to open a few ports to make the Kubernetes setup work on an EC2 instance.
- Control Plance/Master Security Group
 ![image](https://github.com/user-attachments/assets/fe017b10-1f6e-4c5a-900b-c3daff9f60fb)
- Worker Node Security Group
![image](https://github.com/user-attachments/assets/0527725d-1b8d-4ed3-a6f9-269bbe5f3075)
- Access the EC2 instances with ssh using private key
  
## Installation Steps

### 1. Update package index
```bash
sudo apt-get update
```
### 2. Install Docker dependencies
```bash
sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common gpg
```
### 3. Add Docker’s official GPG key
```bash
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
```
### 4. Add Docker’s APT repository
```bash
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```
### 5. Update package index again with Docker repository
```bash
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin -y
```
### 6. Enable and start Docker
```bash
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker $USER
```
### 7. Download and Install cri-dockerd binary
```bash
CRI_DOCKERD_VERSION=0.3.15
mkdir bin
```
```bash
wget https://github.com/Mirantis/cri-dockerd/releases/download/v${CRI_DOCKERD_VERSION}/cri-dockerd-${CRI_DOCKERD_VERSION}.amd64.tgz
sudo tar -C bin -xzf cri-dockerd-${CRI_DOCKERD_VERSION}.amd64.tgz
```
```bash
sudo install -o root -g root -m 0755 bin/cri-dockerd/cri-dockerd /usr/local/bin/cri-dockerd
```
### 8. Create systemd service for cri-dockerd
```bash
cat <<EOF | sudo tee /etc/systemd/system/cri-docker.service
[Unit]
Description=CRI Interface for Docker Application Container Engine
Documentation=https://docs.mirantis.com/
After=network-online.target firewalld.service
Wants=network-online.target
Requires=docker.service

[Service]
ExecStart=/usr/local/bin/cri-dockerd
Restart=always
RestartSec=10s
TimeoutStartSec=0
StartLimitBurst=3
StartLimitInterval=60s

[Install]
WantedBy=multi-user.target
EOF
```
### 9. Create systemd socket for cri-dockerd
```bash
cat <<EOF | sudo tee /etc/systemd/system/cri-docker.socket
[Unit]
Description=CRI Dockerd Socket for the Docker API
PartOf=cri-docker.service

[Socket]
ListenStream=/run/cri-dockerd.sock
SocketMode=0660
SocketUser=root
SocketGroup=docker

[Install]
WantedBy=sockets.target
EOF
```
### 10. Reload systemd and enable cri-dockerd
```bash
sudo systemctl daemon-reload
sudo systemctl enable cri-docker.service
sudo systemctl enable --now cri-docker.socket
sudo systemctl start cri-docker.service
```
### 11. Verify Docker and cri-dockerd services
```bash
systemctl status docker
systemctl status cri-docker.service
```
### 12. Configure Kubernetes official GPG key
```bash
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.31/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.31/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list
```
### 13. Install kubeadm, kubelet, and kubectl
```bash
sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl
sudo systemctl enable --now kubelet
```
### 14. Initialize a Kubernetes cluster using kubeadm init in Control Plance Node
```bash
sudo kubeadm init \
  --apiserver-advertise-address=<private_IP_Address_of_EC2> \
  --pod-network-cidr=10.244.0.0/16 \
  --service-cidr=10.96.0.0/12 \
  --cri-socket=/var/run/cri-dockerd.sock \
  --kubernetes-version=1.31.0
```
### 15. Get the Join Command from the Control Plane Node
```bash
kubeadm token create --print-join-command
```
This will output a command similar to:
```bash
kubeadm join <control-plane-ip>:6443 --token <your-token> --discovery-token-ca-cert-hash sha256:<your-ca-cert-hash>
```
### 16. Apply Calico Manifest
```bash
kubectl apply -f https://docs.projectcalico.org/manifests/calico.yaml
```

### 17. Run the Join Command on the Worker Node
Copy the output from step 15 and execute it on the worker node.
```bash
kubeadm join <control-plane-ip>:6443 --token <your-token> --discovery-token-ca-cert-hash sha256:<your-ca-cert-hash>
```
### 18. Verify the Kubernetes cluster deployment
On the control plane node, check if the worker node has successfully joined:
```bash
kubectl get nodes
kubectl get pods -A
kubectl describe node $(hostname)
```

## Final Notes
- Ensure security group rules allow traffic between nodes.
- If using multiple EC2 instances, configure VPC networking properly.
- If any pods are stuck in CrashLoopBackOff, check logs:
```bash
kubectl logs -n kube-system <pod-name>
```
- This should get your Kubernetes cluster fully operational on AWS EC2 Ubuntu 
