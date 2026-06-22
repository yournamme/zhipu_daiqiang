@echo off
chcp 65001 >nul
cd /d "%~dp0"
call ".venv\Scripts\python.exe" test_proxy.py
