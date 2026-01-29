@echo off
cd /d "%~dp0\.."
echo Starting Notion AI Proxy GUI...
.venv\Scripts\python.exe gui_app.py
pause
