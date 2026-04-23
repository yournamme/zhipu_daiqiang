@echo off
setlocal

cd /d %~dp0

if not exist .venv\Scripts\python.exe (
    echo [glmDesk] Creating virtual environment...
    py -3 -m venv .venv
    .venv\Scripts\python.exe -m pip install --upgrade pip
)

echo [glmDesk] Syncing Python dependencies...
.venv\Scripts\python.exe -m pip install -r requirements.txt

echo [glmDesk] Starting FastAPI server...
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --reload

endlocal
