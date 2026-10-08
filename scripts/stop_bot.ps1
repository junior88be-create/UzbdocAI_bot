# Document AI botini to'xtatish (faqat SHU papkadagi bot).
#   powershell -ExecutionPolicy Bypass -File .\scripts\stop_bot.ps1            - to'xtatish
#   powershell -ExecutionPolicy Bypass -File .\scripts\stop_bot.ps1 -Disable   - to'xtatish va avtomatik ishga tushirish/yangilanishni o'chirish
param([switch]$Disable)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = (Join-Path $scriptDir "run_bot.bat")
Stop-ScheduledTask -TaskName "UzbdocAI_bot" -ErrorAction SilentlyContinue
$all = Get-CimInstance Win32_Process
# run_bot.bat (to'liq yo'li bilan) va u ishga tushirgan python jarayonlari
$runners = $all | Where-Object { $_.Name -eq "cmd.exe" -and $_.CommandLine -and $_.CommandLine.Contains($runner) }
foreach ($r in $runners) {
    $all | Where-Object { $_.ParentProcessId -eq $r.ProcessId } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "To'xtatildi: $($_.Name) PID $($_.ProcessId)"
    }
    Stop-Process -Id $r.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "To'xtatildi: run_bot.bat PID $($r.ProcessId)"
}
if (-not $runners) { Write-Host "Bu papkada ishlayotgan bot topilmadi." }
if ($Disable) {
    Disable-ScheduledTask -TaskName "UzbdocAI_bot" -ErrorAction SilentlyContinue | Out-Null
    Disable-ScheduledTask -TaskName "UzbdocAI_bot_Update" -ErrorAction SilentlyContinue | Out-Null
    Write-Host "Avtomatik ishga tushirish va yangilanish o'chirildi."
}
