param(
    [int]$Port = 8765,
    [string]$Database = "data\agent_mail.db",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$RestartScript = Join-Path $PSScriptRoot "restart_web.ps1"
if (-not (Test-Path -LiteralPath $RestartScript)) {
    throw "Missing restart script: $RestartScript"
}

& $RestartScript -Port $Port -Database $Database
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:$Port/?v=20260913r#/home"
}
