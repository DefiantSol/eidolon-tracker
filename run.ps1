$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot
python -u app.py

$exitCode = $LASTEXITCODE
Write-Host ""
Write-Host "Eidolon Tracker exited with code $exitCode."
Read-Host "Press Enter to close"
