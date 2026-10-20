#!/usr/bin/env bash
# Build each agent image, load into a local kind cluster, deploy, and wait for rollout.
#   ./scripts/deploy_kind.sh            then   python scripts/run_e2e.py --url http://localhost:8080
set -euo pipefail
cd "$(dirname "$0")/.."
CLUSTER=${CLUSTER:-compliance-audit}
AGENTS="gateway crosscheck document regulation reporter"

kind get clusters | grep -qx "$CLUSTER" || kind create cluster --name "$CLUSTER" --config k8s/kind-config.yaml

for a in $AGENTS; do
  docker build -f "agents/$a/Dockerfile" -t "audit-$a:latest" .
  kind load docker-image "audit-$a:latest" --name "$CLUSTER"
done

kubectl apply -k k8s
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  kubectl -n compliance-audit create secret generic anthropic --from-literal=api-key="$ANTHROPIC_API_KEY" \
    --dry-run=client -o yaml | kubectl apply -f -
fi
if [ -n "${SEC_USER_AGENT:-}" ]; then
  kubectl -n compliance-audit patch configmap audit-config -p "{\"data\":{\"SEC_USER_AGENT\":\"$SEC_USER_AGENT\"}}"
fi
kubectl -n compliance-audit rollout restart deploy
kubectl -n compliance-audit rollout status statefulset/redis --timeout=180s
for a in $AGENTS; do kubectl -n compliance-audit rollout status "deploy/$a" --timeout=300s; done
kubectl -n compliance-audit get pods -o wide
echo "gateway: http://localhost:8080"
