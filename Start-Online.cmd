@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0FBLIVE2-Online.exe" (
  echo FBLIVE2-Online.exe was not found. Extract the entire ZIP before starting.
  pause
  exit /b 1
)
start "" "%~dp0FBLIVE2-Online.exe" --portal "https://fb-live-analyzer.vercel.app"
exit /b
