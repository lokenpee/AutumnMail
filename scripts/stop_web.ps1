param([int]$Port = 8765)

$ErrorActionPreference = "Stop"
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $listener) {
    Write-Output "Agent Mail is not running on port $Port."
    exit 0
}

$process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
$commandLine = [string]$process.CommandLine
if ($commandLine -notmatch "(run_web\.py|AgentMail\.exe)" -or $commandLine -notmatch "--port\s+$Port") {
    throw "Port $Port is used by another process: PID $($listener.OwningProcess)"
}

Stop-Process -Id $listener.OwningProcess -Force
Write-Output "Agent Mail stopped (PID $($listener.OwningProcess))."
