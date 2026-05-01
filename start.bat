@echo off
setlocal

cd /d %~dp0

set "APP_HOST=127.0.0.1"
set "APP_PORT=8787"

if exist .env (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if /i "%%A"=="APP_HOST" set "APP_HOST=%%B"
        if /i "%%A"=="APP_PORT" set "APP_PORT=%%B"
    )
)

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%APP_PORT% .*LISTENING"') do (
    if not "%%P"=="" (
        echo [glmDesk] Stopping existing process on port %APP_PORT% - PID %%P ...
        taskkill /F /T /PID %%P >nul 2>&1
    )
)

if not exist .venv\Scripts\python.exe (
    echo [glmDesk] Creating virtual environment...
    py -3 -m venv .venv
    .venv\Scripts\python.exe -m pip install --upgrade pip
)

echo [glmDesk] Syncing Python dependencies...
.venv\Scripts\python.exe -m pip install -r requirements.txt

if exist web\package.json (
    where npm >nul 2>&1
    if errorlevel 1 (
        echo [glmDesk] npm not found; skipping Vue frontend build and using legacy page fallback.
    ) else (
        if not exist web\node_modules (
            echo [glmDesk] Installing Vue frontend dependencies...
            pushd web
            call npm install
            popd
        )
        echo [glmDesk] Building Vue frontend...
        pushd web
        call npm run build
        popd
    )
)
REM ── Dynamic Proxy (optional) ─────────────────────────────────────────────────
REM If dynamic-proxy\dynamic-proxy.exe exists, start it in a background window.
REM Set FALLBACK_PROXY_URL=http://127.0.0.1:17286 in .env to route all accounts
REM (that have no per-account proxy_url) through the rotating proxy pool.
if exist dynamic-proxy\dynamic-proxy.exe (
    echo [glmDesk] Starting dynamic-proxy in background...
    pushd dynamic-proxy
    start "glmDesk-dynamic-proxy" /B dynamic-proxy.exe > ..\.dynamic-proxy.log 2>&1
    popd
    echo [glmDesk] dynamic-proxy started. Log: .dynamic-proxy.log
    echo [glmDesk] Add FALLBACK_PROXY_URL=http://127.0.0.1:17286 to .env to enable proxy rotation.
) else (
    echo [glmDesk] dynamic-proxy.exe not found, skipping proxy rotation.
    echo [glmDesk] Build it with: cd dynamic-proxy ^&^& go build -o dynamic-proxy.exe
)
REM ── FastAPI server ─────────────────────────────────────────────────────────────
echo [glmDesk] Starting FastAPI server...
.venv\Scripts\python.exe -m uvicorn app.main:app --host %APP_HOST% --port %APP_PORT% --reload

endlocal
