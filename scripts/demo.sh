#!/usr/bin/env bash
# Guided live demo. Watches the predictive scaler pre-scale the demo app ahead
# of the load ramp, then shows the reactive trigger catching the surprise spike.
set -euo pipefail

NS=default

say() { echo -e "\n\033[1;36m==> $*\033[0m"; }

say "1. Cluster + components healthy"
kubectl get pods -n "$NS" -l app=demo-app
kubectl get pods -n "$NS" -l app.kubernetes.io/name=predictive-scaler
kubectl get scaledobject -n "$NS"

say "2. What the scaler is forecasting right now"
SCALER=$(kubectl get pod -n "$NS" -l app.kubernetes.io/name=predictive-scaler -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n "$NS" "$SCALER" -- \
  python -c "import urllib.request,json; print(json.load(urllib.request.urlopen('http://localhost:8080/desired-replicas')))" \
  2>/dev/null || echo "  (scaler still warming up — needs history before forecasting)"

say "3. Watch replicas track the predictable ramp (Prophet pre-scales ahead)"
echo "    Watching demo-app replicas for ~3 min. Expect the count to RISE"
echo "    BEFORE load peaks each period — that's the forecast working."
echo "    (Ctrl-C to stop watching and continue.)"
( timeout 180 kubectl get deploy demo-app -n "$NS" -w ) || true

say "4. The surprise spike (Prophet's blind spot, reactive trigger catches it)"
echo "    Around t=900s the load generator fires an unplanned spike the"
echo "    forecaster cannot anticipate. The Prometheus reactive trigger in the"
echo "    ScaledObject scales up in response — the predictive path is a floor,"
echo "    never a ceiling. Watch HPA events:"
kubectl get hpa -n "$NS"
kubectl describe scaledobject -n "$NS" | sed -n '/Triggers/,/Events/p' || true

say "5. Scaler logs (forecast vs decision)"
kubectl logs -n "$NS" -l app.kubernetes.io/name=predictive-scaler --tail=15

say "Demo complete. Capture screenshots of:"
echo "    - kubectl get deploy demo-app -w   (replica count rising ahead of load)"
echo "    - Grafana: demo-app RPS vs replica count overlaid"
echo "    - the spike moment where reactive kicks in"
echo "    Drop them in screenshots/ and reference them in the README."
