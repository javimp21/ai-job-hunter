# Scheduled entry point for Windows Task Scheduler.
# Runs the opportunity pipeline once (fetch monitored ATS -> prefilter -> Jev
# for new/changed eligible jobs -> notifications) and appends the output to a
# monthly log under data\local\logs (Git-ignored). Credentials stay in .env and
# are never passed on the command line or written to the log.
param(
    [int]$MaxJevJobs = 40,
    [int]$MaxNotifications = 10,
    [switch]$NoNotifications,
    # Fetch and preview only: no database writes, no Jev calls, no Telegram.
    [switch]$DryRun
)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$logDir = Join-Path $root "data\local\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("run-" + (Get-Date -Format "yyyy-MM") + ".log")

$runArgs = @(
    "run",
    "--limit-companies", "1000",
    "--max-jobs-per-company", "500",
    "--max-jev-jobs", "$MaxJevJobs",
    "--max-notifications", "$MaxNotifications",
    # Jobs deferred by an earlier run's Jev budget are retried within this
    # run's budget; without it they would stay PENDING forever.
    "--retry-pending"
)
if ($NoNotifications) { $runArgs += "--no-notifications" }
if ($DryRun) { $runArgs += "--dry-run" }

"==== $(Get-Date -Format o) ====" | Out-File -FilePath $log -Append -Encoding utf8
$env:PYTHONIOENCODING = "utf-8"
# Native stderr is merged into the log; keep going so the exit code is recorded.
$ErrorActionPreference = "Continue"
# Prefer the frozen runtime from scripts/deploy-stable.ps1 so work in progress can't break runs.
$exe = Join-Path $root ".venv-stable\Scripts\ai-job-hunter.exe"
if (-not (Test-Path $exe)) { $exe = Join-Path $root ".venv\Scripts\ai-job-hunter.exe" }
& $exe @runArgs 2>&1 |
    ForEach-Object { "$_" } |
    Out-File -FilePath $log -Append -Encoding utf8
$code = $LASTEXITCODE
"exit=$code" | Out-File -FilePath $log -Append -Encoding utf8
# 3 = some sources could not be fetched; the run worked, so no failure notice.
if ($code -eq 3) { $code = 0 }
if (-not $DryRun -and -not $NoNotifications -and (Get-Date).Hour -ge 20) {
    # Evening digest of second-tier jobs; the command itself sends at most one per 20 hours.
    & $exe notify digest 2>&1 | ForEach-Object { "$_" } | Out-File -FilePath $log -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { $code = 1 }
}
if (-not $DryRun -and (Get-Date).Hour -ge 22) {
    # Last run of the day: keep a database backup (newest 14 kept).
    try {
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "scripts\backup-db.ps1") 2>&1 |
            ForEach-Object { "$_" } | Out-File -FilePath $log -Append -Encoding utf8
        if ($LASTEXITCODE -ne 0) { $code = 1 }
    } catch {
        "backup failed: $($_.Exception.Message)" | Out-File -FilePath $log -Append -Encoding utf8
        $code = 1
    }
}
if ($code -ne 0 -and -not $DryRun) {
    # A failed run must not go unnoticed: send a short Telegram notice.
    $notice = "La busqueda programada de las $(Get-Date -Format 'HH:mm') fallo (codigo $code). Detalles en data\local\logs\run-$(Get-Date -Format 'yyyy-MM').log"
    & $exe notify system --text $notice 2>&1 | ForEach-Object { "$_" } | Out-File -FilePath $log -Append -Encoding utf8
}
exit $code
