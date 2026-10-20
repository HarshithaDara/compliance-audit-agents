# Runs every agent as its own OS process against a local Redis (no Docker needed).
# Two crosscheck replicas demonstrate consumer-group load sharing.
#   .\scripts\run_local.ps1            start
#   .\scripts\run_local.ps1 -Stop      stop
param([switch]$Stop)

$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$logs = Join-Path $root "logs"
$pidFile = Join-Path $logs "pids.txt"

if ($Stop) {
    if (Test-Path $pidFile) {
        Get-Content $pidFile | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
        Remove-Item $pidFile
    }
    return
}

New-Item -ItemType Directory -Force $logs | Out-Null
$env:PYTHONPATH = $root
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$env:HEALTH_FILE = Join-Path $logs "healthy"
$procs = @(
    @{ name = "crosscheck-1"; args = @("-m", "agents.crosscheck.agent") },
    @{ name = "crosscheck-2"; args = @("-m", "agents.crosscheck.agent") },
    @{ name = "document-1"; args = @("-m", "agents.document.agent") },
    @{ name = "regulation-1"; args = @("-m", "agents.regulation.agent") },
    @{ name = "reporter-1";   args = @("-m", "agents.reporter.agent") },
    @{ name = "gateway-1";    args = @("-m", "uvicorn", "agents.gateway.app:app", "--port", "8000") }
)
$pids = @()
foreach ($p in $procs) {
    $env:HOSTNAME = $p.name
    $proc = Start-Process -FilePath $py -ArgumentList $p.args -WorkingDirectory $root -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs "$($p.name).out.log") -RedirectStandardError (Join-Path $logs "$($p.name).log")
    $pids += $proc.Id
    Write-Output "started $($p.name) pid $($proc.Id)"
}
$pids | Set-Content $pidFile
