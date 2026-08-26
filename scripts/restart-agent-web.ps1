<##
.SYNOPSIS
Restarts Agent Web on the local network.

.EXAMPLE
.\scripts\restart-agent-web.ps1
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [string]$DataDirectory = (Join-Path (Split-Path $PSScriptRoot -Parent) 'data')
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$logs = Join-Path $DataDirectory 'logs'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found: $python. Run 'uv sync --extra dev' first."
}

$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $listeners) {
    Stop-Process -Id $listener.OwningProcess -Force
}

New-Item -ItemType Directory -Force -Path $logs | Out-Null
$process = Start-Process -FilePath $python `
    -ArgumentList @('-m', 'agent_web.cli', '--data-dir', $DataDirectory, 'serve', '--allow-lan', '--port', $Port) `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logs 'agent-web.out.log') `
    -RedirectStandardError (Join-Path $logs 'agent-web.err.log') `
    -PassThru

for ($attempt = 1; $attempt -le 60; $attempt++) {
    Start-Sleep -Seconds 1
    try {
        $null = Invoke-WebRequest "http://localhost:$Port/" -TimeoutSec 2 -UseBasicParsing
        Write-Host "Agent Web is listening (PID $($process.Id))."
        exit 0
    }
    catch {
        if ($process.HasExited) {
            Get-Content -LiteralPath (Join-Path $logs 'agent-web.err.log') -Raw -ErrorAction SilentlyContinue
            throw "Agent Web exited during startup."
        }
    }
}

throw "Agent Web did not become ready in 60 seconds. Check $(Join-Path $logs 'agent-web.err.log')."
