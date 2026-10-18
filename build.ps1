$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.build-env\Scripts\python.exe')) {
    py -3.12 -m venv .build-env
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create Python build environment.' }
}
$taskPython = Join-Path $PSScriptRoot '.build-env\Scripts\python.exe'
& $taskPython -m pip install -r requirements.txt 'pyinstaller==6.22.3'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $taskPython -m PyInstaller --noconfirm --onefile --windowed --name 'FB-Live-Analyzer' `
    --add-data "$PSScriptRoot\index.html;." `
    --collect-all faster_whisper --collect-all ctranslate2 --collect-all av `
    --collect-all onnxruntime --collect-all yt_dlp --collect-all tokenizers `
    --collect-all huggingface_hub --exclude-module torch --exclude-module tensorflow `
    "$PSScriptRoot\tool.py"
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
Write-Host 'Ready: dist\FB-Live-Analyzer.exe'
