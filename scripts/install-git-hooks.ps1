$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gitDir = Join-Path $repoRoot ".git2"
$hooksDir = Join-Path $gitDir "hooks"

if (-not (Test-Path -LiteralPath $gitDir)) {
  throw "This repository currently uses .git2. Run this after the local Git directory exists."
}

New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null

$hookPath = Join-Path $hooksDir "pre-commit"
$hook = @'
#!/bin/sh
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/security-scan.ps1 -StagedOnly
'@

Set-Content -LiteralPath $hookPath -Value $hook -Encoding ASCII
Write-Host "Installed pre-commit security scan hook." -ForegroundColor Green
