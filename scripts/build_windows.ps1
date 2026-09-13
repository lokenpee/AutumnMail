param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WebDir = Join-Path $Root "web"
$Schema = Join-Path $Root "src\agent_mail\db\schema.sql"
$Launcher = Join-Path $Root "launcher.py"
$Dist = Join-Path $Root "dist\AgentMail"

if (-not $SkipInstall) {
    python -m pip install --upgrade pyinstaller
}

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name "AgentMail" `
    --paths (Join-Path $Root "src") `
    --add-data "$WebDir;web" `
    --add-data "$Schema;agent_mail/db" `
    --distpath (Join-Path $Root "dist") `
    --workpath (Join-Path $Root "build\AgentMail") `
    --specpath (Join-Path $Root "build") `
    $Launcher

Copy-Item -LiteralPath (Join-Path $Root "README.md") -Destination $Dist -Force
Copy-Item -LiteralPath (Join-Path $Root "SECURITY.md") -Destination $Dist -Force
Copy-Item -LiteralPath (Join-Path $Root "LICENSE") -Destination $Dist -Force
@"
@echo off
taskkill /IM AgentMail.exe /F
pause
"@ | Set-Content -LiteralPath (Join-Path $Dist "stop_agent_mail.bat") -Encoding ASCII
Write-Output "Portable build ready: $Dist\AgentMail.exe"
