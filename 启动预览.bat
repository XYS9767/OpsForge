@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 dev.py
) else (
  where py >nul 2>&1
  if not errorlevel 1 (
    py -3 -X utf8 dev.py
  ) else (
    python -X utf8 dev.py
  )
)
echo.
echo 如提示缺少 waitress 等依赖，请按 README 先安装 backend/requirements.txt 与 constraints.txt。
pause