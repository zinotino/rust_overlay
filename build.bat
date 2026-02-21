@echo off
setlocal

echo.
echo  Rust Time Overlay -- Build Script
echo  ===================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Install Python 3.10+ and add it to PATH.
    pause & exit /b 1
)

:: Check PyInstaller
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo  Installing PyInstaller...
    pip install pyinstaller
)

:: Check rustplus
python -c "import rustplus" >nul 2>&1
if errorlevel 1 (
    echo  Installing rustplus...
    pip install rustplus
)

:: Clean previous build
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

echo  Building exe...
echo.
pyinstaller "Rust Time Overlay.spec" --noconfirm

if errorlevel 1 (
    echo.
    echo  BUILD FAILED. Check output above for errors.
    pause & exit /b 1
)

echo.
echo  ===================================
echo  Build complete.
echo  Output: dist\Rust Time Overlay.exe
echo  ===================================
echo.
pause
