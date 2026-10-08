# Document AI Bot - native Windows install (NO Docker Desktop, NO Redis, NO Celery).
# Run in an *Administrator* PowerShell:   powershell -ExecutionPolicy Bypass -File scripts\windows_setup.ps1
# ASCII-only on purpose so it runs the same under any Windows code page.
#
# What it does (safe to re-run):
#   1. finds/installs Python 3.12 and PostgreSQL 16 (via winget)
#   2. creates the database + user, a virtualenv, installs requirements
#   3. writes .env (TASK_BACKEND=inline: the bot processes documents itself)
#   4. runs the database migrations
#   5. registers a Windows Scheduled Task that starts the bot at boot and
#      restarts it if it dies, then starts it now
#   6. stops the PC from going to sleep while plugged in

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Please run this in an Administrator PowerShell." -ForegroundColor Red
    exit 1
}

function Find-Python312 {
    $p = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $p) { return $p.Trim() }
    return $null
}

function Find-Psql {
    $c = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
    if ($c) { return $c.FullName }
    return $null
}

function New-RandomPassword {
    -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
}

# ---- 1. Python 3.12 ----
$py = Find-Python312
if (-not $py) {
    Write-Host "Installing Python 3.12 via winget..."
    winget install -e --id Python.Python.3.12 --scope machine --silent --accept-package-agreements --accept-source-agreements
    $py = Find-Python312
}
if (-not $py) {
    Write-Host "Python 3.12 not found. Install it from https://www.python.org/downloads/ (tick 'Add to PATH'), then re-run." -ForegroundColor Red
    exit 1
}
Write-Host "Python: $py"

# ---- 2. PostgreSQL ----
$psql = Find-Psql
$envExists = Test-Path ".env"
$pgSuperPass = $null
if (-not $psql) {
    Write-Host "Installing PostgreSQL 16 via winget..."
    $pgSuperPass = Read-Host "Choose a password for the PostgreSQL 'postgres' admin account (write it down)"
    winget install -e --id PostgreSQL.PostgreSQL.16 --silent --accept-package-agreements --accept-source-agreements `
        --override "--mode unattended --unattendedmodeui none --superpassword $pgSuperPass --serverport 5432"
    $psql = Find-Psql
}
if (-not $psql) {
    Write-Host "PostgreSQL not found. Install it from https://www.postgresql.org/download/windows/ (keep port 5432), then re-run." -ForegroundColor Red
    exit 1
}
Write-Host "psql: $psql"

# ---- 3. .env + database user/db (first run only) ----
if (-not $envExists) {
    if (-not $pgSuperPass) { $pgSuperPass = Read-Host "PostgreSQL 'postgres' admin password" }
    $appDbPass = New-RandomPassword
    $env:PGPASSWORD = $pgSuperPass

    $role = & $psql -U postgres -h localhost -tAc "SELECT 1 FROM pg_roles WHERE rolname='doc_ai'"
    if ($role -ne "1") {
        & $psql -U postgres -h localhost -c "CREATE ROLE doc_ai LOGIN PASSWORD '$appDbPass'"
    } else {
        & $psql -U postgres -h localhost -c "ALTER ROLE doc_ai WITH PASSWORD '$appDbPass'"
    }
    $db = & $psql -U postgres -h localhost -tAc "SELECT 1 FROM pg_database WHERE datname='doc_ai_bot'"
    if ($db -ne "1") {
        & $psql -U postgres -h localhost -c "CREATE DATABASE doc_ai_bot OWNER doc_ai"
    }
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue

    Write-Host ""
    $botToken  = Read-Host "BOT_TOKEN"
    $geminiKey = Read-Host "GEMINI_API_KEY"
    $adminIds  = Read-Host "Your numeric Telegram ID (admin; comma-separate for several)"
    $lines = @(
        "BOT_TOKEN=$botToken",
        "GEMINI_API_KEY=$geminiKey",
        "GEMINI_MODEL=gemini-3.6-flash",
        "ALLOWED_TELEGRAM_IDS=$adminIds",
        "ADMIN_TELEGRAM_IDS=$adminIds",
        "TASK_BACKEND=inline",
        "DATABASE_URL=postgresql+asyncpg://doc_ai:$appDbPass@localhost:5432/doc_ai_bot",
        "STORAGE_ROOT=storage",
        "FREE_REQUESTS_PER_MONTH=3",
        "LOG_LEVEL=INFO"
    )
    Set-Content -Path ".env" -Value $lines -Encoding ASCII
    Write-Host ".env written."
} else {
    Write-Host ".env already exists - keeping it (delete it to redo database/user setup)."
}

# ---- 4. virtualenv + dependencies ----
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & $py -m venv .venv
}
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip install failed - see the output above." -ForegroundColor Red
    exit 1
}

# ---- 5. migrations ----
& ".venv\Scripts\alembic.exe" upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host "Database migration failed - check that the PostgreSQL service is running and .env DATABASE_URL is right." -ForegroundColor Red
    exit 1
}

# ---- 6. auto-start at boot + auto-restart ----
$taskName = "UzbdocAI_bot"
$action    = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$root\scripts\run_bot.bat`"" -WorkingDirectory $root
$trigger   = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName $taskName

# ---- 7. never sleep while plugged in ----
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0

Write-Host ""
Write-Host "Waiting 25s for the bot to start..."
Start-Sleep -Seconds 25
if (Test-Path "bot.log") { Get-Content "bot.log" -Tail 12 }
try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8081/health" -TimeoutSec 5
    Write-Host "Health check: $($r.StatusCode) $($r.Content)" -ForegroundColor Green
} catch {
    Write-Host "Health check failed - look at bot.log in $root" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Done. Log: $root\bot.log   Stop: Stop-ScheduledTask -TaskName $taskName   Start: Start-ScheduledTask -TaskName $taskName"
