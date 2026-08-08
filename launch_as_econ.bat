@echo off
REM ============================================
REM  as-econ launcher (Windows)
REM  Save this file INSIDE your as-econ project
REM  folder, right next to Home.py
REM ============================================

cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

echo Starting as-econ ...
streamlit run Home.py

echo.
echo App closed. Press any key to close this window.
pause >nul
