@echo off
title Python Requirements Installer
color 0A

echo ===================================================
echo     Checking and Installing Python Dependencies[cite: 1]
echo ===================================================
echo.

:: Check if Python is installed and accessible[cite: 1]
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [ERROR] Python is not installed or not added to your system PATH.[cite: 1]
    echo Please install Python and check the "Add to PATH" box during setup.[cite: 1]
    echo.
    pause
    exit /b
)

:: Upgrade pip first to avoid legacy installation errors[cite: 1]
echo [1/2] Upgrading pip to the latest version...[cite: 1]
python -m pip install --upgrade pip
echo.

:: Install the required libraries for the PBR Converter
echo [2/2] Installing required libraries (numpy and Pillow)...
python -m pip install numpy Pillow
echo.
echo ===================================================
echo [SUCCESS] All requirements installed successfully![cite: 1]
echo ===================================================

echo.
pause