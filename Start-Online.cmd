@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0FB-Live-Analyzer-Online.exe" (
  echo FB-Live-Analyzer-Online.exe was not found. Extract the entire ZIP before starting.
  pause
  exit /b 1
)
start "" "%~dp0FB-Live-Analyzer-Online.exe" --portal "https://fb-live-analyzer.vercel.app"
exit /b
