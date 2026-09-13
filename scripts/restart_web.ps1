param(
    [int]$Port = 8765,
    [string]$Database = "data\agent_mail.db"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DatabasePath = Join-Path $ProjectRoot $Database
$Launcher = Join-Path $ProjectRoot "scripts\run_web.py"

if (-not (Test-Path -LiteralPath $Launcher)) {
    throw "Cannot find launcher: $Launcher"
}
if (-not (Test-Path -LiteralPath $DatabasePath)) {
    throw "Cannot find database: $DatabasePath"
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    $commandLine = [string]$process.CommandLine
    if ($commandLine -notmatch "run_web\.py" -or $commandLine -notmatch "--port\s+$Port") {
        throw "Port $Port is used by another process: PID $($listener.OwningProcess)"
    }
    Stop-Process -Id $listener.OwningProcess -Force
    Start-Sleep -Milliseconds 500
}

$backgroundLauncher = Join-Path $ProjectRoot "scripts\start_web_background.py"
python $backgroundLauncher --port $Port --db $DatabasePath

Start-Sleep -Seconds 2
$newListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $newListener) {
    throw "Server failed to start on port $Port"
}

Write-Output "Agent Mail restarted"
Write-Output "PID: $($newListener.OwningProcess)"
Write-Output "URL: http://127.0.0.1:$Port/?v=20260913r#/home"
