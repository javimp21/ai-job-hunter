# Daily PostgreSQL backup for the local Docker database.
# Dumps inside the container (custom format) and copies the file out, so no
# binary data passes through a PowerShell pipeline. Keeps the newest 14 dumps
# under data\local\backups (Git-ignored). Restore with:
#   docker compose cp <dump> postgres:/tmp/restore.dump
#   docker compose exec postgres pg_restore -U ai_job_hunter -d ai_job_hunter --clean /tmp/restore.dump
param([int]$Keep = 14)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$dir = Join-Path $root "data\local\backups"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$name = "ai_job_hunter-$(Get-Date -Format 'yyyyMMdd-HHmm').dump"

docker compose exec -T postgres pg_dump -U ai_job_hunter -d ai_job_hunter -Fc -f "/tmp/$name"
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed (exit $LASTEXITCODE)" }
docker compose cp "postgres:/tmp/$name" (Join-Path $dir $name)
if ($LASTEXITCODE -ne 0) { throw "copying the dump failed (exit $LASTEXITCODE)" }
docker compose exec -T postgres rm -f "/tmp/$name" | Out-Null

Get-ChildItem $dir -Filter "ai_job_hunter-*.dump" | Sort-Object Name -Descending | Select-Object -Skip $Keep |
    Remove-Item -Force
$size = [math]::Round((Get-Item (Join-Path $dir $name)).Length / 1MB, 2)
Write-Host "Backup written: $name ($size MB)"
