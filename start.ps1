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

# Everything below re-runs automatically after a `git pull` that changed dependencies or source files.
function Newer($a, $b) { (Test-Path $a) -and (-not (Test-Path $b) -or (Get-Item $a).LastWriteTime -gt (Get-Item $b).LastWriteTime) }
$stamp = "backend\.venv-local\.installed"
if (-not (Test-Path "backend\.venv-local\Scripts\uvicorn.exe") -or (Newer "backend\pyproject.toml" $stamp)) {
  Write-Host "==> Installing the backend"
  if (-not (Test-Path "backend\.venv-local\Scripts\python.exe")) { & cmd /c "$py -m venv backend\.venv-local" }
  & backend\.venv-local\Scripts\python.exe -m pip install --quiet --upgrade pip
  & backend\.venv-local\Scripts\python.exe -m pip install --quiet -e backend
  New-Item -ItemType File -Force $stamp | Out-Null
}

if (-not (Test-Path "frontend\node_modules") -or (Newer "frontend\package-lock.json" "frontend\node_modules\.package-lock.json")) {
  Write-Host "==> Installing portal packages"
  Push-Location frontend
  npm ci --no-audit --no-fund --loglevel=error
  Pop-Location
}

$dist = "frontend\dist\index.html"
$changed = -not (Test-Path $dist)
if (-not $changed) {
  $built = (Get-Item $dist).LastWriteTime
  $changed = [bool](Get-ChildItem frontend\src, frontend\index.html, frontend\package-lock.json -Recurse -File | Where-Object { $_.LastWriteTime -gt $built } | Select-Object -First 1)
}
if ($changed) {
  Write-Host "==> Building the portal"
  Push-Location frontend
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
