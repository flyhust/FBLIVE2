param([switch]$Online)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.build-env\Scripts\python.exe')) {
    py -3.12 -m venv .build-env
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create Python build environment.' }
}
$taskPython = Join-Path $PSScriptRoot '.build-env\Scripts\python.exe'
& $taskPython -m pip install -r requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $taskPython scripts\make_notices.py
if ($LASTEXITCODE -ne 0) { throw 'License notice generation failed.' }
$taskName = if ($Online) { 'FBLIVE2-Online' } else { 'FBLIVE2' }
& $taskPython -m PyInstaller --noconfirm --onefile --windowed --name $taskName `
    --add-data "$PSScriptRoot\index.html;." `
    --add-data "$PSScriptRoot\analysis_templates.json;." `
    --collect-all faster_whisper --collect-all ctranslate2 --collect-all av `
    --collect-all onnxruntime --collect-all yt_dlp --collect-all tokenizers `
    --collect-all huggingface_hub --exclude-module torch --exclude-module tensorflow `
    "$PSScriptRoot\tool.py"
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
Copy-Item -LiteralPath 'THIRD_PARTY_NOTICES.txt' -Destination 'dist\THIRD_PARTY_NOTICES.txt' -Force
if ($Online) {
    Copy-Item -LiteralPath 'Start-Online.cmd','线上工作台使用说明.md' -Destination 'dist' -Force
}
Write-Host "Ready: dist\$taskName.exe"
