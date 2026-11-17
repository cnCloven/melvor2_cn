# Build a one-file console exe. Requires Python + pip on the BUILD machine only.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install --upgrade pip pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --console `
  --name Melvor2CN `
  --noupx `
  --hidden-import enable_zh_cn_locale `
  --hidden-import patch_pck_translations `
  melvor2_cn_app.py

Write-Host "Built: $PSScriptRoot\dist\Melvor2CN.exe"
Get-Item "$PSScriptRoot\dist\Melvor2CN.exe" | Select-Object FullName, Length, LastWriteTime
