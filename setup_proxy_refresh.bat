@echo off
chcp 65001 >nul
powershell -ExecutionPolicy Bypass -File "%~dp0setup_proxy_refresh.ps1"
