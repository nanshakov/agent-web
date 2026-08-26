param(
    [Parameter(Mandatory)] [string]$RepositoryUrl,
    [string]$Branch = 'main'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
& $python -m agent_web.cli --data-dir (Join-Path $root 'data') configure-update `
    --repository-url $RepositoryUrl --branch $Branch
