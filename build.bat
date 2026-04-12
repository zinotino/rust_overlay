@echo off
setlocal enabledelayedexpansion

echo.
echo  Rust Time Overlay -- Build Script
echo  ===================================
echo.

:: Use the Python that is on PATH — same one the user runs scripts with
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Install Python 3.10+ and add it to PATH.
    pause & exit /b 1
)

for /f "tokens=*" %%i in ('python -c "import sys; print(sys.executable)"') do set PYTHON=%%i
echo  Using Python: %PYTHON%
echo.

:: Install / upgrade dependencies into the correct interpreter
echo  Checking dependencies...
"%PYTHON%" -m pip install --upgrade pyinstaller rustplus --quiet
if errorlevel 1 (
    echo  ERROR: Failed to install dependencies.
    pause & exit /b 1
)

:: Clean previous build artifacts
echo  Cleaning previous build...
if exist dist   rmdir /s /q dist
if exist build  rmdir /s /q build

:: Build
echo  Building exe...
echo.
"%PYTHON%" -m PyInstaller "Rust Time Overlay.spec" --noconfirm

if errorlevel 1 (
    echo.
    echo  BUILD FAILED. Check output above for errors.
    pause & exit /b 1
)

:: Copy freshly built exe into the release folder
if not exist release mkdir release
copy /y "dist\Rust Time Overlay.exe" "release\Rust Time Overlay.exe" >nul
echo  Copied exe to release\

echo.
echo  ===================================
echo  Build complete!
echo  Output: dist\Rust Time Overlay.exe
echo         release\Rust Time Overlay.exe
echo.
echo  To distribute: zip release\Rust Time Overlay.exe and release\source\
echo  Do NOT include rust_overlay_config.json in any release package.
echo  ===================================
echo.
pause
