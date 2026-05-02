@echo off
setlocal EnableExtensions EnableDelayedExpansion

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

rem Dynamic proxy is optional. It is started only when FALLBACK_PROXY_URL points to local dynamic-proxy.
set "SHOULD_START_DYNAMIC_PROXY=0"
if not "%FALLBACK_PROXY_URL%"=="" (
    set "PROXY_CHECK=%FALLBACK_PROXY_URL:127.0.0.1:1728=%"
    if not "!PROXY_CHECK!"=="%FALLBACK_PROXY_URL%" set "SHOULD_START_DYNAMIC_PROXY=1"
    set "PROXY_CHECK=%FALLBACK_PROXY_URL:localhost:1728=%"
    if not "!PROXY_CHECK!"=="%FALLBACK_PROXY_URL%" set "SHOULD_START_DYNAMIC_PROXY=1"
)

if "%SHOULD_START_DYNAMIC_PROXY%"=="1" (
    if exist dynamic-proxy (
        echo [glmDesk] Stopping existing dynamic-proxy processes...
        taskkill /F /T /IM dynamic-proxy.exe >nul 2>&1

        where go >nul 2>&1
        if errorlevel 1 (
            echo [glmDesk] Go not found; using existing dynamic-proxy.exe if available.
        ) else (
            echo [glmDesk] Building dynamic-proxy.exe from current source...
            pushd dynamic-proxy
            go build -o dynamic-proxy.exe .
            if errorlevel 1 (
                popd
                echo [glmDesk] Failed to build dynamic-proxy.exe. FastAPI will still start, but proxy health may be degraded.
                goto after_dynamic_proxy
            )
            popd
        )
    )

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

:after_dynamic_proxy

echo [glmDesk] Starting FastAPI server...
.venv\Scripts\python.exe -m uvicorn app.main:app --host %APP_HOST% --port %APP_PORT% --reload

endlocal
