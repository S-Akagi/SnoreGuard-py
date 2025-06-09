@echo off

echo Build SnoreGuard with PyInstaller
echo =====================================

echo Cleaning previous builds...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo Building with spec file...
uv run pyinstaller SnoreGuard.spec --clean

echo Build completed!
echo The executable is located in: dist/SnoreGuard.exe
pause