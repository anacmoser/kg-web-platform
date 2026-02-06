@echo off
echo ========================================
echo   KG Web Platform - Startup Script
echo ========================================
echo.

REM Check if .env exists
if not exist "backend\.env" (
    echo [WARNING] backend\.env not found. Creating from .env.example...
    copy "backend\.env.example" "backend\.env"
    echo.
    echo Please edit backend\.env and add your OPENAI_API_KEY
    echo Press any key to continue after editing...
    pause
)

REM Check if virtual environment exists (check root first, then backend)
if exist "venv\Scripts\activate.bat" (
    echo [INFO] Using existing venv from root folder
    set VENV_PATH=venv
) else if exist "backend\venv\Scripts\activate.bat" (
    echo [INFO] Using existing venv from backend folder
    set VENV_PATH=backend\venv
) else (
    echo [SETUP] Creating Python virtual environment in backend\venv...
    python -m venv backend\venv
    set VENV_PATH=backend\venv
    echo [OK] Virtual environment created
    echo.
)

REM Install backend dependencies
echo [SETUP] Installing backend dependencies...
call %VENV_PATH%\Scripts\activate.bat
pip install -r backend\requirements.txt
echo [OK] Backend dependencies installed
echo.

REM Install frontend dependencies
if not exist "frontend\node_modules" (
    echo [SETUP] Installing frontend dependencies...
    cd frontend
    call npm install
    cd ..
    echo [OK] Frontend dependencies installed
    echo.
)

echo ========================================
echo   Setup complete! Starting servers...
echo ========================================
echo.
echo Backend: http://localhost:5000
echo Frontend: http://localhost:5173
echo.
echo Press Ctrl+C to stop both servers
echo.

REM Start backend in new window
start "KG Platform - Backend" cmd /k "cd /d %CD%\backend && ..\%VENV_PATH%\Scripts\activate.bat && python wsgi.py"

REM Wait a bit for backend to start
timeout /t 3 /nobreak > nul

REM Start frontend in new window
start "KG Platform - Frontend" cmd /k "cd /d %CD%\frontend && npm run dev"

echo.
echo [OK] Both servers started in separate windows
echo You can close this window
