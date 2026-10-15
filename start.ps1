# Qeonix Smart Licence Services: one-command local run (Windows PowerShell).
# Needs Python 3.12+ and Node.js 20+. First run installs everything (a few minutes); later runs start in seconds.
# Run:  powershell -ExecutionPolicy Bypass -File .\start.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Port = if ($env:PORT) { $env:PORT } else { "8000" }

$py = $null
foreach ($c in @("py -3.13", "py -3.12", "python")) {
  try { $v = & cmd /c "$c -c ""import sys; print(sys.version_info >= (3, 12))"" 2>nul"; if ($v -eq "True") { $py = $c; break } } catch {}
}
if (-not $py) { Write-Host "Python 3.12 or newer is required: https://www.python.org/downloads/"; exit 1 }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Write-Host "Node.js 20 or newer is required: https://nodejs.org/"; exit 1 }

if (-not (Test-Path "backend\.venv-local\Scripts\uvicorn.exe")) {
  Write-Host "==> Installing the backend (first run only)"
  & cmd /c "$py -m venv backend\.venv-local"
  & backend\.venv-local\Scripts\python.exe -m pip install --quiet --upgrade pip
  & backend\.venv-local\Scripts\python.exe -m pip install --quiet -e backend
}

if (-not (Test-Path "frontend\dist\index.html")) {
  Write-Host "==> Building the portal"
  Push-Location frontend
  if (-not (Test-Path node_modules)) { npm ci --no-audit --no-fund --loglevel=error }
  npx vite build --logLevel error
  Pop-Location
}

$env:QEONIX_SERVE_FRONTEND = "true"
$env:QEONIX_SEED_DEMO_ON_START = "true"
$env:QEONIX_DEMO_MODE = "true"
$env:QEONIX_FRONTEND_BASE_URL = "http://localhost:$Port"
$env:QEONIX_UAEPASS_ISSUER = "http://localhost:$Port/mock-uaepass"
$env:QEONIX_UAEPASS_REDIRECT_URI = "http://localhost:$Port/api/auth/callback"

Write-Host "==> Starting on http://localhost:$Port  (guided demo: http://localhost:$Port/demo, press Ctrl+C to stop)"
Start-Job { Start-Sleep 4; Start-Process "http://localhost:$using:Port/demo" } | Out-Null
Set-Location backend
& .\.venv-local\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port $Port
