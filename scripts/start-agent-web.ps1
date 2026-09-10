# Run the native backend and bundled React UI in one foreground process.
[CmdletBinding()]
param([int]$Port = 8765, [switch]$AllowLan)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$dataDirectory = Join-Path $projectRoot 'data'
$serveArguments = @('run', '--project', $projectRoot, 'agent-web', '--data-dir', $dataDirectory, 'serve', '--port', "$Port")
if ($AllowLan) { $serveArguments += '--allow-lan' }
& uv @serveArguments
exit $LASTEXITCODE
