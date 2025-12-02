@echo off
echo Updating pySCHaulingAssistant...
echo.

REM Pull latest changes
git pull
if errorlevel 1 (
    echo.
    echo WARNING: Git pull failed. Continuing anyway...
    echo.
)

REM Run the application
call run.bat
