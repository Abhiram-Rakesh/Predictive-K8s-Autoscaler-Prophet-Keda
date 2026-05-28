#!/usr/bin/env bash
# Deploy the demo app, the load generator, the monitoring glue, and the
# predictive scaler Helm chart. Pass the scaler image as $1 (defaults to the
# public GHCR image).
set -euo pipefail

IMAGE="${1:-ghcr.io/abhiram-rakesh/predictive-scaler:latest}"
REPO="${IMAGE%:*}"
TAG="${IMAGE##*:}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "$TAG" == "latest" ]]; then
  echo "WARN: deploying :latest. For production, pin to a SHA tag from CI:"
  echo "      ./scripts/deploy.sh ghcr.io/<owner>/predictive-scaler:<git-sha>"
fi

echo "==> demo app + service"
kubectl apply -f "$ROOT/k8s/demo-workloads/demo-app.yaml"

echo "==> demo-app ServiceMonitor"
kubectl apply -f "$ROOT/k8s/monitoring/demo-app-servicemonitor.yaml"

echo "==> load generator (script as ConfigMap, then deployment)"
kubectl create configmap loadgen-script \
  --from-file=loadgen.py="$ROOT/scripts/loadgen.py" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "$ROOT/k8s/demo-workloads/load-generator.yaml"

echo "==> predictive scaler (Helm)"
helm upgrade --install predictive-scaler "$ROOT/helm/predictive-scaler" \
  --namespace default \
  --set image.repository="$REPO" \
  --set image.tag="$TAG" \
  --wait

echo "==> waiting for rollout"
kubectl rollout status deploy/predictive-scaler -n default
kubectl rollout status deploy/demo-app -n default

echo "==> deployed. ScaledObject:"
kubectl get scaledobject -n default
