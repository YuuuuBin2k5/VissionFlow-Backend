param(
  [switch]$StagedOnly
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gitDir = Join-Path $repoRoot ".git2"

if (Test-Path -LiteralPath $gitDir) {
  $gitArgs = @("--git-dir=$gitDir", "--work-tree=$repoRoot")
} else {
  $gitArgs = @("-C", $repoRoot)
}

if ($StagedOnly) {
  $files = git @gitArgs diff --cached --name-only --diff-filter=ACMRT
} else {
  $files = git @gitArgs ls-files
}

$secretPatterns = [ordered]@{
  "telegram_bot_token" = "\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"
  "google_api_key" = "AIza[0-9A-Za-z_-]{20,}"
  "google_oauth_client_secret" = "GOCSPX-[0-9A-Za-z_-]+"
  "google_oauth_access_token" = "ya29\.[0-9A-Za-z_-]+"
  "google_oauth_refresh_token" = "1//[0-9A-Za-z_-]+"
}

$hits = @()

foreach ($relativePath in $files) {
  if ([string]::IsNullOrWhiteSpace($relativePath)) {
    continue
  }

  $fullPath = Join-Path $repoRoot $relativePath
  if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
    continue
  }

  try {
    $content = Get-Content -LiteralPath $fullPath -Raw -ErrorAction Stop
  } catch {
    continue
  }

  foreach ($patternName in $secretPatterns.Keys) {
    $matches = [regex]::Matches($content, $secretPatterns[$patternName])
    if ($matches.Count -gt 0) {
      $hits += [pscustomobject]@{
        File = $relativePath
        Pattern = $patternName
        Count = $matches.Count
      }
    }
  }
}

if ($hits.Count -gt 0) {
  Write-Host "Potential secrets found. Values are intentionally hidden." -ForegroundColor Red
  $hits | Sort-Object File, Pattern | Format-Table -AutoSize
  exit 1
}

Write-Host "Security scan passed: no known token patterns found." -ForegroundColor Green
