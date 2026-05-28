#!/usr/bin/env bash
# Open Grafana + Prometheus locally. Ctrl-C stops both.
set -euo pipefail

echo "Grafana:    http://localhost:3000  (admin / admin)"
echo "Prometheus: http://localhost:9090"
echo "Press Ctrl-C to stop."

kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80 >/tmp/pf-grafana.log 2>&1 &
G=$!
kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090 >/tmp/pf-prom.log 2>&1 &
P=$!

trap 'kill $G $P 2>/dev/null' INT TERM
wait
