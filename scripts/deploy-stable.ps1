# Installs the committed HEAD (never uncommitted work) into .venv-stable, which
# the scheduled run and the bot use. Development in .venv / the working tree can
# then be half-finished without breaking scheduled runs.
# Run after committing and testing a change:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-stable.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$git = @("-c", "safe.directory=$($root -replace '\\', '/')")
$commit = (& git @git rev-parse --short HEAD).Trim()
$dirty = & git @git status --porcelain --untracked-files=no
if ($dirty) { Write-Host "Note: uncommitted changes exist; deploying committed HEAD $commit only." }

$build = Join-Path $root "data\local\stable-build"
if (Test-Path $build) { Remove-Item -Recurse -Force $build }
New-Item -ItemType Directory -Force -Path $build | Out-Null
$archive = Join-Path $build "source.zip"
& git @git archive --format=zip -o $archive HEAD
Expand-Archive -Path $archive -DestinationPath (Join-Path $build "src") -Force

# Never replace the runtime under a scheduled run: it would crash mid-run.
function Get-StableRun {
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "venv-stable" -and $_.CommandLine -match "\srun\s" }
}
$waited = 0
while ((Get-StableRun) -and $waited -lt 60) {
    if ($waited -eq 0) { Write-Host "A scheduled run is in progress; waiting for it to finish (up to 60 min)..." }
    Start-Sleep -Seconds 60
    $waited++
}
if (Get-StableRun) { throw "A scheduled run is still in progress; deploy aborted, nothing changed." }

# The bot runs from .venv-stable; Windows cannot replace an executable in use.
$botTask = Get-ScheduledTask -TaskName "AI Job Hunter Bot" -ErrorAction SilentlyContinue
$botProcesses = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "venv-stable" -and $_.CommandLine -match "\sbot(\s|$)" }
$botWasRunning = $botTask -and ($botTask.State -eq "Running" -or $botProcesses)
if ($botWasRunning) {
    Stop-ScheduledTask -TaskName "AI Job Hunter Bot"
    $botProcesses | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

try {
    $venv = Join-Path $root ".venv-stable"
    if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
        & (Join-Path $root ".venv\Scripts\python.exe") -m venv $venv
    }
    $python = Join-Path $venv "Scripts\python.exe"
    & $python -m pip install -q --upgrade pip
    & $python -m pip install -q --force-reinstall --no-deps "$(Join-Path $build 'src')"
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
    & $python -m pip install -q "$(Join-Path $build 'src')[jev,llm]"
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
    Remove-Item -Recurse -Force $build

    "$commit $(Get-Date -Format o)" | Out-File -FilePath (Join-Path $root "data\local\stable-version.txt") -Encoding utf8
    Write-Host "Stable runtime now at commit $commit."
} finally {
    # Bring the bot back even if the install failed, so buttons keep working.
    if ($botWasRunning) {
        Start-ScheduledTask -TaskName "AI Job Hunter Bot"
        Write-Host "Bot restarted."
    }
}
