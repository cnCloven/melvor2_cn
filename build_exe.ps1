# Build a one-file console exe. Requires Python + pip on the BUILD machine only.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install --upgrade pip pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --console `
  --name Melvo2CN `
  --noupx `
  --add-data "backups/project.binary.bak;backups" `
  --add-data "backups/project.binary.dirmeta.json;backups" `
  --hidden-import enable_zh_cn_locale `
  --hidden-import patch_pck_translations `
  melvo2_cn_app.py

Write-Host "Built: $PSScriptRoot\dist\Melvo2CN.exe"
Get-Item "$PSScriptRoot\dist\Melvo2CN.exe" | Select-Object FullName, Length, LastWriteTime
