# Windows equivalent of deploy_kind.sh. Requires Docker Desktop running, kind and kubectl on PATH.
#   .\scripts\deploy_kind.ps1           then   python scripts\run_e2e.py --url http://127.0.0.1:8080
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$cluster = if ($env:CLUSTER) { $env:CLUSTER } else { "compliance-audit" }
$agents = "gateway", "crosscheck", "regulation", "reporter"

if (-not ((kind get clusters) -contains $cluster)) {
    kind create cluster --name $cluster --config k8s/kind-config.yaml
}
foreach ($a in $agents) {
    docker build -f "agents/$a/Dockerfile" -t "audit-${a}:latest" .
    if ($LASTEXITCODE) { throw "docker build failed for $a" }
    kind load docker-image "audit-${a}:latest" --name $cluster
}
kubectl apply -k k8s
if ($env:ANTHROPIC_API_KEY) {
    kubectl -n compliance-audit create secret generic anthropic --from-literal=api-key=$env:ANTHROPIC_API_KEY `
        --dry-run=client -o yaml | kubectl apply -f -
}
kubectl -n compliance-audit rollout restart deploy
kubectl -n compliance-audit rollout status statefulset/redis --timeout=180s
foreach ($a in $agents) { kubectl -n compliance-audit rollout status "deploy/$a" --timeout=300s }
kubectl -n compliance-audit get pods -o wide
Write-Output "gateway: http://127.0.0.1:8080"
