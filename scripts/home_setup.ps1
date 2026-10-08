# Document AI Bot - home server setup (run in PowerShell on the home PC).
# ASCII-only on purpose so it runs the same under any Windows code page.
#
# What it does: checks Git/Docker, clones the repo, writes .env, starts the
# full stack (postgres, redis, bot, worker, beat) with docker compose, and
# stops the PC from sleeping. Nothing here touches Railway.

$ErrorActionPreference = "Continue"
$repoUrl = "https://github.com/junior88be-create/UzbdocAI_bot.git"
$target  = "C:\UzbdocAI_bot"

function Need($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "MISSING: $cmd -> $hint" -ForegroundColor Red
        exit 1
    }
}

Need docker "install Docker Desktop: https://www.docker.com/products/docker-desktop/"

docker info | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker is installed but not running. Start Docker Desktop, wait until it says 'Engine running', then re-run this script." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "IMPORTANT: only ONE copy of the bot may poll Telegram at a time." -ForegroundColor Yellow
Write-Host "The Railway bot must be stopped before this one starts, or both will fail with 'Conflict: terminated by other getUpdates request'."
$answer = Read-Host "Is the Railway bot already stopped? (y/n)"
if ($answer -ne "y") {
    Write-Host "Stop the Railway service first, then re-run." -ForegroundColor Red
    exit 1
}

$projectRoot = Split-Path -Parent $PSScriptRoot
if (Test-Path (Join-Path $projectRoot "docker-compose.yml")) {
    # Running from an unzipped copy of the project - use it as-is.
    Set-Location $projectRoot
} elseif (Test-Path "$target\.git") {
    Write-Host "Repo exists - pulling latest..."
    git -C $target pull
    Set-Location $target
} else {
    git clone $repoUrl $target
    Set-Location $target
}

if (-not (Test-Path ".env")) {
    Write-Host ""
    Write-Host "Creating .env (values are stored only on this PC)..."
    $botToken = Read-Host "BOT_TOKEN"
    $geminiKey = Read-Host "GEMINI_API_KEY"
    $adminIds = Read-Host "Your numeric Telegram ID (admin; comma-separate for several)"
    $lines = @(
        "BOT_TOKEN=$botToken",
        "GEMINI_API_KEY=$geminiKey",
        "GEMINI_MODEL=gemini-3.6-flash",
        "ALLOWED_TELEGRAM_IDS=$adminIds",
        "ADMIN_TELEGRAM_IDS=$adminIds",
        "FREE_REQUESTS_PER_MONTH=3",
        "LOG_LEVEL=INFO"
    )
    Set-Content -Path ".env" -Value $lines -Encoding ASCII
} else {
    Write-Host ".env already exists - keeping it."
}

Write-Host ""
Write-Host "Building and starting the stack (first build takes a few minutes)..."
docker compose up -d --build
if ($LASTEXITCODE -ne 0) {
    Write-Host "docker compose failed - see the output above." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Keeping the PC awake while plugged in..."
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0

Write-Host ""
docker compose ps
Write-Host ""
Write-Host "Done. Check logs with:  docker compose logs -f bot worker" -ForegroundColor Green
Write-Host "Also enable: Docker Desktop > Settings > General > 'Start Docker Desktop when you sign in', and set Windows to auto-login or run as a service so it survives reboots."
