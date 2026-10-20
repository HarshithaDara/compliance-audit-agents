# Windows equivalent of deploy_kind.sh. Requires Docker Desktop running, kind and kubectl on PATH.
#   .\scripts\deploy_kind.ps1           then   python scripts\run_e2e.py --url http://127.0.0.1:8080
#
# Native tools (docker, kind) write progress to stderr. Windows PowerShell 5.1 turns that into
# errors under $ErrorActionPreference = "Stop" when output is redirected, so check exit codes instead.
Set-Location (Split-Path -Parent $PSScriptRoot)
$cluster = if ($env:CLUSTER) { $env:CLUSTER } else { "compliance-audit" }
$agents = "gateway", "crosscheck", "document", "regulation", "reporter"

function Invoke-Checked([string]$What, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit $LASTEXITCODE)" }
}

$existing = cmd /c "kind get clusters 2>nul"
if (-not ($existing -contains $cluster)) {
    Invoke-Checked "kind create cluster" { kind create cluster --name $cluster --config k8s/kind-config.yaml }
}
foreach ($a in $agents) {
    Invoke-Checked "docker build $a" { docker build -q -f "agents/$a/Dockerfile" -t "audit-${a}:latest" . }
    Invoke-Checked "kind load $a" { kind load docker-image "audit-${a}:latest" --name $cluster }
}
Invoke-Checked "kubectl apply" { kubectl apply -k k8s }
if ($env:ANTHROPIC_API_KEY) {
    kubectl -n compliance-audit create secret generic anthropic --from-literal=api-key=$env:ANTHROPIC_API_KEY `
        --dry-run=client -o yaml | kubectl apply -f -
}
if ($env:SEC_USER_AGENT) {
    $patch = @{ data = @{ SEC_USER_AGENT = $env:SEC_USER_AGENT } } | ConvertTo-Json -Compress
    kubectl -n compliance-audit patch configmap audit-config --type merge -p $patch
}
Invoke-Checked "rollout restart" { kubectl -n compliance-audit rollout restart deploy }
Invoke-Checked "redis rollout" { kubectl -n compliance-audit rollout status statefulset/redis --timeout=180s }
foreach ($a in $agents) {
    Invoke-Checked "$a rollout" { kubectl -n compliance-audit rollout status "deploy/$a" --timeout=300s }
}
kubectl -n compliance-audit get pods -o wide
Write-Output "gateway: http://127.0.0.1:8080"
