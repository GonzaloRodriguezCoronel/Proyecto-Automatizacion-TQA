@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Primero haz doble clic en instalar_facil_windows.bat.
  pause
  exit /b 1
)
.venv\Scripts\python.exe iniciar_tqa_facil.py
if errorlevel 1 (
  echo.
  echo No se pudo iniciar TQA. Copia el error de arriba para revisarlo.
  pause
)
