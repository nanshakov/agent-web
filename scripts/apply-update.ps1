$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
& (Join-Path $root '.venv\Scripts\python.exe') -m agent_web.cli `
    --data-dir (Join-Path $root 'data') update apply --yes
& (Join-Path $PSScriptRoot 'restart-agent-web.ps1')
