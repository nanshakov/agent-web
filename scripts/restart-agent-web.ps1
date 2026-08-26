<##
.SYNOPSIS
Restarts Agent Web on the local network.

.EXAMPLE
.\scripts\restart-agent-web.ps1
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [string]$DataDirectory
)

$ErrorActionPreference = 'Stop'
$scriptDirectory = Split-Path -Parent $PSCommandPath
$projectRoot = Split-Path -Parent $scriptDirectory
if ([string]::IsNullOrWhiteSpace($DataDirectory)) {
    $DataDirectory = Join-Path $projectRoot 'data'
}
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$logs = Join-Path $DataDirectory 'logs'

function Stop-AgentProcessTree([int]$ListenerProcessId) {
    $allProcesses = Get-CimInstance Win32_Process
    $byId = @{}
    foreach ($item in $allProcesses) { $byId[$item.ProcessId] = $item }

    # The uv virtualenv launcher is the parent of the process that owns the
    # listening socket. Walk upward to terminate that launcher too.
    $rootId = $ListenerProcessId
    $cursor = $byId[$rootId]
    while ($cursor -and $byId.ContainsKey($cursor.ParentProcessId)) {
        $parent = $byId[$cursor.ParentProcessId]
        if ($parent.CommandLine -notlike '*agent_web.cli*') { break }
        $rootId = $parent.ProcessId
        $cursor = $parent
    }

    $queue = [Collections.Generic.Queue[int]]::new()
    $queue.Enqueue($rootId)
    $tree = [Collections.Generic.List[int]]::new()
    while ($queue.Count) {
        $current = $queue.Dequeue()
        $tree.Add($current)
        foreach ($child in $allProcesses | Where-Object ParentProcessId -eq $current) {
            $queue.Enqueue($child.ProcessId)
        }
    }
    foreach ($processId in ($tree | Sort-Object -Descending)) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found: $python. Run 'uv sync --extra dev' first."
}

$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $listeners) {
    Stop-AgentProcessTree $listener.OwningProcess
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
        $null = Invoke-WebRequest "http://127.0.0.1:$Port/" -TimeoutSec 2 -UseBasicParsing
        Write-Host "Agent Web is listening (PID $($process.Id))."
        exit 0
    }
    catch { }
}

throw "Agent Web did not become ready in 60 seconds. Check $(Join-Path $logs 'agent-web.err.log')."
