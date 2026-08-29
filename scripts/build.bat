@echo off
chcp 65001 >nul
rem リポジトリルートへ移動（どこから実行しても同じ結果にする）
cd /d "%~dp0.."

echo [1/3] 依存関係を lock どおりに同期します...
uv sync --locked --no-dev --group build
if errorlevel 1 exit /b 1

echo [2/3] PyInstaller でビルドします...
uv run --no-sync pyinstaller SnoreGuard.spec --clean
if errorlevel 1 exit /b 1

echo [3/3] 完了: dist\SnoreGuard.exe
