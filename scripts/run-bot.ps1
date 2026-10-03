# Keeps the Telegram cover-letter bot (`ai-job-hunter bot`) running.
# Output is appended to a monthly log under data\local\logs (Git-ignored); if the
# process exits for any reason it is restarted after 30 seconds. Stop with Ctrl+C.
# Credentials stay in .env and are never passed on the command line or logged.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$logDir = Join-Path $root "data\local\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$env:PYTHONIOENCODING = "utf-8"
# Native stderr is merged into the log; keep going so the exit code is recorded.
$ErrorActionPreference = "Continue"

while ($true) {
    $log = Join-Path $logDir ("bot-" + (Get-Date -Format "yyyy-MM") + ".log")
    "==== $(Get-Date -Format o) ====" | Out-File -FilePath $log -Append -Encoding utf8
    & (Join-Path $root ".venv\Scripts\ai-job-hunter.exe") bot 2>&1 |
        ForEach-Object { "$_" } |
        Out-File -FilePath $log -Append -Encoding utf8
    "exit=$LASTEXITCODE; restarting in 30 seconds" | Out-File -FilePath $log -Append -Encoding utf8
    Start-Sleep -Seconds 30
}
