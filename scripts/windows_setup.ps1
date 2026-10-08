# Document AI Bot - Windows'da (Docker Desktop'siz, Redis/Celery'siz) doimiy ishlaydigan qilib o'rnatish.
# Administrator PowerShell'da (loyiha papkasida):
#   powershell -ExecutionPolicy Bypass -File .\scripts\windows_setup.ps1
# Qayta ishga tushirish xavfsiz: mavjud .env va baza saqlanadi.
# Skript faqat ASCII: istalgan Windows kod sahifasida bir xil ishlaydi.
$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$dir = Split-Path -Parent $scriptDir
Set-Location $dir
$TaskName = "UzbdocAI_bot"
$UpdateTask = "UzbdocAI_bot_Update"
$repoUrl = "https://github.com/junior88be-create/UzbdocAI_bot.git"

function Step($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function New-RandomPassword { -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ }) }
function Find-Python312 {
    $p = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $p) { return $p.Trim() }
    return $null
}
function Find-FreePort($start) {
    foreach ($p in $start..($start + 50)) {
        if (-not (Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue)) { return $p }
    }
    return $start
}
function Find-Psql {
    $c = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
    if ($c) { return $c.FullName }
    return $null
}
function Refresh-Path { $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "PowerShell'ni Administrator sifatida oching (PostgreSQL o'rnatish va Windows yoqilganda ishga tushirish uchun kerak)." -ForegroundColor Red
    exit 1
}

# 1. Python 3.12
Step "Python 3.12 tekshirilmoqda"
$py = Find-Python312
if (-not $py) {
    Write-Host "Python 3.12 o'rnatilmoqda (winget)..."
    winget install -e --id Python.Python.3.12 --scope machine --silent --accept-package-agreements --accept-source-agreements | Out-Null
    Refresh-Path
    $py = Find-Python312
}
if (-not $py) {
    Write-Host "Python 3.12 topilmadi. https://www.python.org/downloads/ dan o'rnating ('Add python.exe to PATH' ni belgilang), keyin skriptni qayta ishga tushiring." -ForegroundColor Red
    exit 1
}
Write-Host "Python: $py"

# 2. PostgreSQL
Step "PostgreSQL tekshirilmoqda"
$psql = Find-Psql
$pgSuperPass = $null
if (-not $psql) {
    Write-Host "PostgreSQL 16 o'rnatilmoqda (winget)..."
    $pgSuperPass = Read-Host "PostgreSQL 'postgres' admin paroli uchun o'zingiz parol o'ylab toping (yozib qo'ying)"
    winget install -e --id PostgreSQL.PostgreSQL.16 --silent --accept-package-agreements --accept-source-agreements `
        --override "--mode unattended --unattendedmodeui none --superpassword $pgSuperPass --serverport 5432" | Out-Null
    $psql = Find-Psql
}
if (-not $psql) {
    Write-Host "PostgreSQL topilmadi. https://www.postgresql.org/download/windows/ dan o'rnating (5432 port), keyin skriptni qayta ishga tushiring." -ForegroundColor Red
    exit 1
}
Write-Host "psql: $psql"

# 3. .env va baza (faqat birinchi marta)
Step ".env va baza"
if (-not (Test-Path ".env")) {
    if (-not $pgSuperPass) { $pgSuperPass = Read-Host "PostgreSQL 'postgres' admin paroli" }
    $appDbPass = New-RandomPassword
    $env:PGPASSWORD = $pgSuperPass
    $role = & $psql -U postgres -h localhost -tAc "SELECT 1 FROM pg_roles WHERE rolname='doc_ai'"
    if ($role -ne "1") {
        & $psql -U postgres -h localhost -c "CREATE ROLE doc_ai LOGIN PASSWORD '$appDbPass'" | Out-Null
    } else {
        & $psql -U postgres -h localhost -c "ALTER ROLE doc_ai WITH PASSWORD '$appDbPass'" | Out-Null
    }
    $db = & $psql -U postgres -h localhost -tAc "SELECT 1 FROM pg_database WHERE datname='doc_ai_bot'"
    if ($db -ne "1") {
        & $psql -U postgres -h localhost -c "CREATE DATABASE doc_ai_bot OWNER doc_ai" | Out-Null
    }
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue

    $botToken  = Read-Host "BOT_TOKEN (BotFather'dan)"
    $geminiKey = Read-Host "GEMINI_API_KEY"
    $adminIds  = Read-Host "O'zingizning Telegram ID raqamingiz (admin; bir nechta bo'lsa vergul bilan)"
    $lines = @(
        "BOT_TOKEN=$botToken",
        "GEMINI_API_KEY=$geminiKey",
        "GEMINI_MODEL=gemini-3.6-flash",
        "ALLOWED_TELEGRAM_IDS=$adminIds",
        "ADMIN_TELEGRAM_IDS=$adminIds",
        "TASK_BACKEND=inline",
        "DATABASE_URL=postgresql+asyncpg://doc_ai:$appDbPass@localhost:5432/doc_ai_bot",
        "HEALTH_PORT=$(Find-FreePort 8081)",
        "STORAGE_ROOT=storage",
        "FREE_REQUESTS_PER_MONTH=3",
        "LOG_LEVEL=INFO"
    )
    Set-Content -Path ".env" -Value $lines -Encoding ASCII
    Write-Host ".env yozildi."
} else {
    Write-Host ".env bor - o'zgartirilmadi (bazani qaytadan sozlash uchun .env ni o'chirib, skriptni qayta ishga tushiring)."
}

# 4. Virtual muhit va kutubxonalar
Step "Kutubxonalar o'rnatilmoqda (2-5 daqiqa)"
if (-not (Test-Path ".venv\Scripts\python.exe")) { & $py -m venv .venv }
& ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
if ($LASTEXITCODE -ne 0) { Write-Host "Kutubxonalarni o'rnatib bo'lmadi" -ForegroundColor Red; exit 1 }
Write-Host "Tayyor"

# 5. Baza migratsiyalari
Step "Baza tayyorlanmoqda"
& ".venv\Scripts\alembic.exe" upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host "Migratsiya bajarilmadi - PostgreSQL xizmati ishlayotganini va .env dagi DATABASE_URL to'g'riligini tekshiring." -ForegroundColor Red
    exit 1
}

# 6. Git (GitHub'dan avtomatik yangilanish uchun) - zip'dan ochilgan papka ham git papkaga aylanadi
Step "Git sozlanmoqda"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git o'rnatilmoqda (winget)..."
    winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
    Refresh-Path
}
$gitOk = $false
if (Get-Command git -ErrorAction SilentlyContinue) {
    git config --global --add safe.directory ($dir -replace '\\', '/')
    if (-not (Test-Path ".git")) { git init -q; git remote add origin $repoUrl }
    git remote set-url origin $repoUrl
    git fetch -q origin main 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        git reset -q --hard origin/main   # .env, .venv, storage git'da yo'q - tegilmaydi
        $gitOk = $true
    } else {
        Write-Host "GitHub'ga ulanib bo'lmadi - avtomatik yangilanish o'chiq. Internetni tekshirib, skriptni qayta ishga tushiring." -ForegroundColor Yellow
    }
} else {
    Write-Host "Git topilmadi - avtomatik yangilanish o'chiq (bot baribir ishlaydi)." -ForegroundColor Yellow
}

# 7. Avtomatik ishga tushirish (Windows yoqilganda, hech kim kirmasa ham)
Step "Avtomatik ishga tushirish sozlanmoqda"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scriptDir "stop_bot.ps1") | Out-Null
$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$scriptDir\run_hidden.vbs`"" -WorkingDirectory $dir
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Document AI Telegram boti" -Force | Out-Null
Write-Host "Vazifa '$TaskName' yaratildi: Windows yoqilganda (kirish shart emas)"

if ($gitOk) {
    $upAction = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$scriptDir\run_update_hidden.vbs`"" -WorkingDirectory $dir
    $upTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
        -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
    Register-ScheduledTask -TaskName $UpdateTask -Action $upAction -Trigger $upTrigger -Settings $settings `
        -Principal $principal -Description "Document AI bot: GitHub'dan yangilanish" -Force | Out-Null
    Write-Host "Har 5 daqiqada GitHub'dan yangilanish tekshiriladi (jurnal: update.log)"
}

powercfg /change standby-timeout-ac 0 | Out-Null
powercfg /change hibernate-timeout-ac 0 | Out-Null

# 8. Hozir ishga tushirish
Step "Bot ishga tushirilmoqda"
Start-ScheduledTask -TaskName $TaskName
$started = $false
foreach ($i in 1..12) {  # 60 soniyagacha kutamiz
    Start-Sleep -Seconds 5
    $log = Get-Content "bot.log" -Tail 60 -ErrorAction SilentlyContinue
    if ($log -match "Run polling") { $started = $true; break }
}
$log | Select-Object -Last 8 | ForEach-Object { Write-Host $_ }
if ($started) {
    Write-Host "`nBot ishlayapti! Kompyuter yoqilganda u o'zi ishga tushadi, yangilanishlar GitHub'dan o'zi keladi." -ForegroundColor Green
} else {
    Write-Host "`nBot hali ishga tushmadi - bir daqiqadan so'ng bot.log ni tekshiring." -ForegroundColor Yellow
}
