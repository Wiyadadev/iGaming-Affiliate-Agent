param([int]$Port = 8000, [switch]$Install)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if ($pythonCommand) { & $pythonCommand.Source -m venv .venv }
    elseif ($pyCommand) { & $pyCommand.Source -3 -m venv .venv }
    elseif (Test-Path -LiteralPath $bundledPython) { & $bundledPython -m venv .venv }
    else { throw 'Install Python 3.12 or newer, then run this script again.' }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
    $Install = $true
}
if ($Install) {
    & $pythonExe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
Write-Host "Workspace: http://127.0.0.1:$Port/dashboard/"
Write-Host "Portfolio demo: http://127.0.0.1:$Port/dashboard/?demo=1"
& $pythonExe -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port $Port
