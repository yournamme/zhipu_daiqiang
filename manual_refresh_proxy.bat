@echo off
chcp 65001 >nul
echo ========================================
echo   抢购前手动刷新代理（消耗 50 个 IP）
echo ========================================
echo.
echo 用途：抢购前 2-3 分钟运行，拉取新鲜代理
echo 注意：每次运行消耗 50 个 IP 额度
echo.
echo 按 Ctrl+C 取消，按任意键继续...
pause >nul

cd /d "%~dp0"
call ".venv\Scripts\python.exe" refresh_kuaidaili.py

echo.
echo ----------------------------------------
echo 下一步：
echo   1. 重启 start.bat（如果已在运行，先关掉）
echo   2. 打开 http://127.0.0.1:8787
echo   3. 右上角出口模式切到「代理池」
echo   4. 确认可用代理数 ^> 0
echo ----------------------------------------
pause
