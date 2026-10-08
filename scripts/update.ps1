# Document AI Bot - pull the latest version from GitHub and restart (Windows install).
# Run in an *Administrator* PowerShell:
#     powershell -ExecutionPolicy Bypass -File scripts\update.ps1
# Add -Schedule once to ALSO update automatically every night at 04:00:
#     powershell -ExecutionPolicy Bypass -File scripts\update.ps1 -Schedule
#
# Works whether the folder came from `git clone` or from the zip (a zip copy is
# converted to a git checkout in place). Your .env, .venv, storage\ and bot.log
# are not tracked by git, so they are never touched. Tracked files are reset to
# exactly what is on GitHub - do not hand-edit code in this folder.
# ASCII-only on purpose so it runs the same under any Windows code page.

param([switch]$Schedule)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$repoUrl  = "https://github.com/junior88be-create/UzbdocAI_bot.git"
$taskName = "UzbdocAI_bot"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Please run this in an Administrator PowerShell." -ForegroundColor Red
    exit 1
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Git via winget..."
    winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git not found. Install it from https://git-scm.com/download/win and re-run." -ForegroundColor Red
    exit 1
}

# The folder may be owned by a different Windows user than this admin shell.
git config --global --add safe.directory ($root -replace '\\', '/')

if (-not (Test-Path ".git")) {
    Write-Host "Converting this folder to a git checkout..."
    git init -q
    git remote add origin $repoUrl
}

$before = (git rev-parse --short HEAD 2>$null)
git fetch origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host "Could not reach GitHub - bot left running on the current version." -ForegroundColor Red
    exit 1
}
$latest = (git rev-parse --short origin/main)
if ($before -eq $latest) {
    Write-Host "Already up to date ($latest)." -ForegroundColor Green
} else {
    Write-Host "Updating $before -> $latest ..."
    git reset --hard origin/main

    Write-Host "Stopping the bot..."
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath -like "$root\.venv\*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

    & ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "pip install failed - bot NOT restarted. See output above." -ForegroundColor Red
        exit 1
    }
    & ".venv\Scripts\alembic.exe" upgrade head
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Database migration failed - bot NOT restarted. See output above." -ForegroundColor Red
        exit 1
    }

    Start-ScheduledTask -TaskName $taskName
    Write-Host "Bot restarted on $latest." -ForegroundColor Green
}

if ($Schedule) {
    $act = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$root\scripts\update.ps1`"" -WorkingDirectory $root
    $trg = New-ScheduledTaskTrigger -Daily -At 4:00AM
    $prn = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName "UzbdocAI_update" -Action $act -Trigger $trg -Principal $prn -Force | Out-Null
    Write-Host "Nightly auto-update registered (04:00). Remove with: Unregister-ScheduledTask -TaskName UzbdocAI_update -Confirm:`$false"
}
