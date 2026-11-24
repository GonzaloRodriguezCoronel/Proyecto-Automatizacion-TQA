@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo No existe .venv. Ejecuta instalar_windows.bat primero.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8022
pause
