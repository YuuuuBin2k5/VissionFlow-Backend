param(
  [switch]$InstallDependencies
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$serviceRoot = Join-Path $repoRoot "services\control-plane"
$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }

Push-Location $serviceRoot
try {
  if ($InstallDependencies) {
    & $python -m pip install --upgrade pip
    & $python -m pip install -r requirements-dev.txt
  }

  & $python -m ruff check app alembic tests
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

  & $python -m compileall -q app alembic tests
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

  & $python -m unittest discover -s tests -v
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

  Write-Host "VisionFlow Control Plane verification passed." -ForegroundColor Green
}
finally {
  Pop-Location
}
