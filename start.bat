@echo off
setlocal

:: Get the directory where the script is located
set SCRIPT_DIR=%~dp0

:: Navigate to the deploy directory
cd /d "%SCRIPT_DIR%deploy"

echo Starting services from deploy/docker-compose.yml...
docker-compose up -d --build

echo Services started.
echo Backend API: http://localhost:8000
echo Frontend UI: http://localhost:3000

endlocal