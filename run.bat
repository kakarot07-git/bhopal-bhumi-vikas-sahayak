@echo off
REM Double-click to start Bhumi Vikas Sahayak, then open http://localhost:8000
cd /d "%~dp0"
if "%ANTHROPIC_API_KEY%"=="" if exist .env for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"
python -m pip install -q -r requirements.txt
start "" http://localhost:8000
python -m app.server
