param([switch]$EnableGpu)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { throw "Orbit's Python environment is missing at $python" }
Push-Location $PSScriptRoot
try {
    $options = @()
    if ($EnableGpu) { $options += '--enable-gpu' }
    & $python -u -m orbit_backend.launch @options
    $result = $LASTEXITCODE
} finally { Pop-Location }
exit $result
