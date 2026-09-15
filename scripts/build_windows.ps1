param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WebDir = Join-Path $Root "web"
$Schema = Join-Path $Root "src\agent_mail\db\schema.sql"
$Launcher = Join-Path $Root "launcher.py"
$Dist = Join-Path $Root "dist\AgentMail"
$SecretCheck = Join-Path $Root "scripts\check_secrets.py"
$ReleaseDir = Join-Path $Root "release"
$Archive = Join-Path $ReleaseDir "AgentMail-Windows.zip"

# GitHub source archives contain tracked files. Refuse to build a release if
# any tracked source file resembles private runtime data or a common secret.
python $SecretCheck --all-tracked
if ($LASTEXITCODE -ne 0) {
    throw "Secret scan failed; release was not built."
}

# A previous local run may have created user data next to the executable.
# Never carry that runtime directory into a distributable build.
$RuntimeData = Join-Path $Dist "data"
if (Test-Path -LiteralPath $RuntimeData) {
    Remove-Item -LiteralPath $RuntimeData -Recurse -Force
}

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

$forbidden = Get-ChildItem -LiteralPath $Dist -Recurse -File -Force |
    Where-Object { $_.Name -match '(?i)(\.db(-wal|-shm)?$|\.sqlite3?$|\.log$|^\.env|credentials|secret)' }
if ($forbidden) {
    $paths = ($forbidden | ForEach-Object { $_.FullName }) -join ", "
    throw "Refusing to publish a build containing runtime or secret files: $paths"
}

New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null
Compress-Archive -LiteralPath $Dist -DestinationPath $Archive -Force
Write-Output "Release archive ready: $Archive"
