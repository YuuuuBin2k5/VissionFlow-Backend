param(
  [switch]$StagedOnly
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gitArgs = @("-c", "safe.directory=$($repoRoot.Replace('\', '/'))", "-C", $repoRoot)

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
  "object_storage_literal_credential" = '(?i)(?:aws_access_key_id|aws_secret_access_key|VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID|VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY)["'']?\s*(?:=|:|,)\s*["''][a-f0-9]{32,64}["'']'
}

$hits = @()

foreach ($relativePath in $files) {
  if ([string]::IsNullOrWhiteSpace($relativePath)) {
    continue
  }

  $fullPath = Join-Path $repoRoot $relativePath
  # Token regexes are text checks; random MP4/image bytes produce false positives.
  # Generated media must separately be excluded from any proposed commit.
  if ([IO.Path]::GetExtension($relativePath) -match '^\.(mp4|mp3|m4a|png|jpg|jpeg|gif|webp|woff2?|ttf|ico|pdf|zip|exe|dll|pyc)$') {
    continue
  }
  if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
    continue
  }

  try {
    $content = [string](Get-Content -LiteralPath $fullPath -Raw -ErrorAction Stop)
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
