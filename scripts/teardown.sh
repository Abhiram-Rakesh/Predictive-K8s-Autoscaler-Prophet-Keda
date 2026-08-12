#!/usr/bin/env bash
# Tear down everything and stop billing. Order matters: Helm releases first so
# any LoadBalancer-type services release their AWS ELBs, then namespaces, then
# terraform destroy — otherwise the VPC delete hangs on leftover ENIs.
set -euo pipefail

read -r -p "This destroys the EKS cluster and all demo resources. Type 'destroy' to confirm: " ans
[[ "$ans" == "destroy" ]] || { echo "aborted"; exit 1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> uninstalling Helm releases"
helm uninstall predictive-scaler -n default 2>/dev/null || true
helm uninstall monitoring -n monitoring 2>/dev/null || true
helm uninstall keda -n keda 2>/dev/null || true

echo "==> deleting demo workloads"
kubectl delete -f "$ROOT/k8s/demo-workloads/load-generator.yaml" 2>/dev/null || true
kubectl delete configmap loadgen-script -n default 2>/dev/null || true
kubectl delete -f "$ROOT/k8s/demo-workloads/demo-app.yaml" 2>/dev/null || true

echo "==> deleting namespaces"
kubectl delete namespace monitoring keda 2>/dev/null || true

echo "==> waiting 60s for AWS to release ENIs / load balancers"
sleep 60

echo "==> terraform destroy"
cd "$ROOT/terraform" && terraform destroy -auto-approve

echo "==> teardown complete. Verify no cluster remains:"
echo "    aws eks list-clusters --region \${AWS_REGION:-ap-south-1}"
