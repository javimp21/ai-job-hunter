<#
.SYNOPSIS
  Sends a leads file to the production server and activates the boards it finds. Used by the weekly funded-startups routine.

.DESCRIPTION
  The only things this script does on the server are fixed: import the file, resolve (three passes), sync the sources and
  auto-activate at most 20 boards. The file must live in private/leads/ and end in .local.json; its content is validated
  before anything is sent. Nothing is sent to any person or company: these commands only register and watch public boards.
#>
param(
    [Parameter(Mandatory = $true)][string]$File
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$allowedDir = (Join-Path $root 'private\leads')
$full = (Resolve-Path -LiteralPath $File).Path
if (-not $full.StartsWith($allowedDir + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "The file must be inside private\leads\ ($allowedDir)."
}
$name = [IO.Path]::GetFileName($full)
if ($name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.local\.json$') {
    throw "Unsafe file name: $name (use letters, digits, dots, dashes; ending in .local.json)."
}

# Validate the content before sending anything.
$data = Get-Content -LiteralPath $full -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $data.leads -or $data.leads.Count -lt 1 -or $data.leads.Count -gt 40) {
    throw 'The file needs between 1 and 40 leads.'
}
foreach ($lead in $data.leads) {
    if (-not $lead.company_name -or -not $lead.careers_url -or $lead.careers_url -notmatch '^https://') {
        throw "Every lead needs a company_name and an https careers_url ($($lead.company_name))."
    }
}

$key = Join-Path $env:USERPROFILE '.ssh\oracle_job_hunter'
$server = 'ubuntu@82.70.78.125'
$remoteDir = '/opt/ai-job-hunter/shared/private'

& scp -i $key -o BatchMode=yes $full "${server}:${remoteDir}/${name}"
if ($LASTEXITCODE -ne 0) { throw 'scp failed.' }

$remote = @"
set -e
cd /opt/ai-job-hunter/shared
set -a; . ./.env; set +a
V=/opt/ai-job-hunter/current/.venv/bin
`$V/python -m ai_job_hunter.company_leads_cli import --file private/$name
for i in 1 2 3; do `$V/python -m ai_job_hunter.company_leads_cli resolve --limit 100 | tail -4; done
`$V/ai-job-hunter sources sync | tail -2
`$V/ai-job-hunter sources auto-activate --limit 20
"@
$remote = $remote -replace "`r", ''
& ssh -i $key -o BatchMode=yes $server $remote
if ($LASTEXITCODE -ne 0) { throw 'The remote import failed.' }
