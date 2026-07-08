$ErrorActionPreference = "Stop"
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name LeagueAutoAccept --icon assets\icon.ico --paths src `
  src\laa\__main__.py
Write-Host "Built dist\LeagueAutoAccept.exe"
