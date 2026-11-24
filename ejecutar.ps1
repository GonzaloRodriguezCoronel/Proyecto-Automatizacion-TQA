Set-Location $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
  Write-Host 'Instala primero: .\instalar_windows.bat'
  exit 1
}
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8022
