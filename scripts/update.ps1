# Document AI Bot: GitHub'dan yangi kodni olish va botni qayta ishga tushirish.
# Task Scheduler har 5 daqiqada chaqiradi. Qo'lda:  powershell -ExecutionPolicy Bypass -File .\scripts\update.ps1
# Yangi kod tekshiruvdan o'tmasa yoki baza migratsiyasi xato bersa - avvalgi
# ishlayotgan versiyaga qaytiladi va rad etilgan versiya qayta sinalmaydi.
# .env, .venv, storage\ va jurnallar git'da yo'q - ularga tegilmaydi.
$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$dir = Split-Path -Parent $scriptDir
Set-Location $dir
$logFile = Join-Path $dir "update.log"
function Log($t) { "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $t" | Out-File -FilePath $logFile -Append -Encoding utf8 }

# Bir vaqtda ikkita yangilanish ishlamasin
$lock = Join-Path $dir ".update.lock"
if ((Test-Path $lock) -and ((Get-Date) - (Get-Item $lock).LastWriteTime).TotalMinutes -lt 15) { exit 0 }
New-Item -ItemType File -Path $lock -Force | Out-Null
try {
    $git = (Get-Command git -ErrorAction SilentlyContinue).Source
    if (-not $git) { Log "git topilmadi - yangilanish o'tkazib yuborildi"; exit 1 }

    & git fetch -q origin main 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Log "GitHub'ga ulanib bo'lmadi (internet?)"; exit 1 }
    $old = (& git rev-parse HEAD).Trim()
    $new = (& git rev-parse origin/main).Trim()
    if ($old -eq $new) { exit 0 }  # yangi kod yo'q
    $badFile = Join-Path $dir ".update_bad"
    if ((Test-Path $badFile) -and ((Get-Content $badFile -Raw).Trim() -eq $new)) { exit 0 }  # bu versiya avval rad etilgan

    Log "Yangi versiya: $($new.Substring(0,7)) (eski: $($old.Substring(0,7)))"
    $reqChanged = (& git diff --name-only $old $new) -contains "requirements.txt"
    & git reset -q --hard $new   # .env va holat fayllari (git'da yo'q) tegmaydi

    $py = Join-Path $dir ".venv\Scripts\python.exe"
    $alembic = Join-Path $dir ".venv\Scripts\alembic.exe"
    if ($reqChanged) {
        Log "requirements.txt o'zgargan - kutubxonalar yangilanmoqda"
        & $py -m pip install -q -r requirements.txt 2>&1 | Out-Null
    }

    # Tekshiruv: sintaksis va importlar (bot ishga tushmaydi). Har qanday xato = muvaffaqiyatsiz.
    $ok = $false
    try {
        if (-not (Test-Path $py)) { throw "Python (.venv) topilmadi" }
        $files = & git ls-files "*.py"
        $global:LASTEXITCODE = 1
        & $py -m py_compile @files 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "sintaksis xatosi" }
        $global:LASTEXITCODE = 1
        & $py -c "import app.main" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "import xatosi" }
        $ok = $true
    } catch {
        Log "Tekshiruv: $_"
    }
    if (-not $ok) {
        Log "XATO: yangi kod tekshiruvdan o'tmadi - eski versiyaga qaytildi (keyingi versiyagacha kutiladi)"
        & git reset -q --hard $old
        $new | Out-File -FilePath $badFile -Encoding ascii -NoNewline
        if ($reqChanged) { & $py -m pip install -q -r requirements.txt 2>&1 | Out-Null }
        exit 1
    }

    # Botni to'xtatib, baza migratsiyasini qo'llab, qayta ishga tushirish
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scriptDir "stop_bot.ps1") | Out-Null
    Start-Sleep -Seconds 3
    $global:LASTEXITCODE = 1
    & $alembic upgrade head 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        Log "XATO: baza migratsiyasi bajarilmadi - eski versiyaga qaytildi"
        & git reset -q --hard $old
        $new | Out-File -FilePath $badFile -Encoding ascii -NoNewline
        if ($reqChanged) { & $py -m pip install -q -r requirements.txt 2>&1 | Out-Null }
        Start-ScheduledTask -TaskName "UzbdocAI_bot" -ErrorAction SilentlyContinue
        exit 1
    }
    Start-ScheduledTask -TaskName "UzbdocAI_bot" -ErrorAction SilentlyContinue
    Log "Yangilandi va bot qayta ishga tushirildi: $($new.Substring(0,7))"
}
finally {
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
}
