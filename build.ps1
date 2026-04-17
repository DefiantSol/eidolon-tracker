$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

python -m PyInstaller `
  --noconfirm `
  --onedir `
  --windowed `
  --name EidolonTracker `
  --add-data "static;static" `
  --add-data "data;data" `
  app.py

Write-Host ""
Write-Host "Built: $PSScriptRoot\dist\EidolonTracker\EidolonTracker.exe"
Write-Host "Share the whole dist\EidolonTracker folder, not just the .exe."
Write-Host "No personal tracker.db is copied into the release folder."
