@echo off
setlocal

cd /d %~dp0

set "APP_HOST=127.0.0.1"
set "APP_PORT=8787"
set "FALLBACK_PROXY_URL="

if exist .env (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if /i "%%A"=="APP_HOST" set "APP_HOST=%%B"
        if /i "%%A"=="APP_PORT" set "APP_PORT=%%B"
        if /i "%%A"=="FALLBACK_PROXY_URL" set "FALLBACK_PROXY_URL=%%B"
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
REM dynamic-proxy is only needed when FALLBACK_PROXY_URL points to the local proxy pool.
REM Without FALLBACK_PROXY_URL, GLM Desk runs direct network requests and ignores KDL_/PROXY_POOL_ settings.
set "SHOULD_START_DYNAMIC_PROXY=0"
if not "%FALLBACK_PROXY_URL%"=="" (
    echo %FALLBACK_PROXY_URL% | findstr /I /C:"127.0.0.1:1728" /C:"localhost:1728" >nul
    if not errorlevel 1 set "SHOULD_START_DYNAMIC_PROXY=1"
)

if "%SHOULD_START_DYNAMIC_PROXY%"=="1" (
    if exist dynamic-proxy\dynamic-proxy.exe (
        echo [glmDesk] Starting dynamic-proxy in background for FALLBACK_PROXY_URL=%FALLBACK_PROXY_URL% ...
        pushd dynamic-proxy
        start "glmDesk-dynamic-proxy" /B dynamic-proxy.exe > ..\.dynamic-proxy.log 2>&1
        popd
        echo [glmDesk] dynamic-proxy started. Log: .dynamic-proxy.log
    ) else (
        echo [glmDesk] FALLBACK_PROXY_URL points to local dynamic-proxy, but dynamic-proxy.exe was not found.
        echo [glmDesk] Build it with: cd dynamic-proxy ^&^& go build -o dynamic-proxy.exe
        echo [glmDesk] FastAPI will still start, but proxy health will be degraded until dynamic-proxy is available.
    )
) else (
    if "%FALLBACK_PROXY_URL%"=="" (
        echo [glmDesk] FALLBACK_PROXY_URL is empty; skipping dynamic-proxy. Direct network mode is enabled.
    ) else (
        echo [glmDesk] FALLBACK_PROXY_URL=%FALLBACK_PROXY_URL% does not point to local dynamic-proxy; skipping local dynamic-proxy startup.
    )
)
REM ── FastAPI server ─────────────────────────────────────────────────────────────
echo [glmDesk] Starting FastAPI server...
.venv\Scripts\python.exe -m uvicorn app.main:app --host %APP_HOST% --port %APP_PORT% --reload

endlocal
