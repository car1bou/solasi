param(
    [Parameter(Mandatory=$true)][string]$Python,
    [string]$BuildDirectory = ''
)
$ErrorActionPreference = 'Stop'
$source = Split-Path $PSScriptRoot
if (-not $BuildDirectory) { $BuildDirectory = Join-Path $source '.local-state\windows-build' }
New-Item -ItemType Directory -Path $BuildDirectory -Force | Out-Null
Set-Location $source
function Checked-Run([string]$Executable,[string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('Command failed: ' + $Executable) }
}
$venv = Join-Path $BuildDirectory 'venv'
if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) { Checked-Run $Python @('-m','venv',$venv) }
$buildPython = Join-Path $venv 'Scripts\python.exe'
Checked-Run $buildPython @('-m','pip','install','-r',(Join-Path $source 'requirements-windows-build.lock'))
$cmake = Join-Path $venv 'Scripts\cmake.exe'
$cache = Join-Path $BuildDirectory 'downloads'
New-Item -ItemType Directory -Path $cache -Force | Out-Null
$modelSource = Join-Path $cache 'llama-source.tar.gz'
$downloadCode = 'from pathlib import Path; import sys; from lecture_study.runtime import download_verified; from scripts.build_windows_models import SOURCE_URL,SOURCE_SHA256; download_verified(dict(url=SOURCE_URL,sha256=SOURCE_SHA256,bytes=38195486),Path(sys.argv[1]))'
Checked-Run $buildPython @('-c',$downloadCode,$modelSource)
$engines = Join-Path $BuildDirectory 'model-engines'
if (-not (Test-Path (Join-Path $engines 'receipt.json'))) { Checked-Run $buildPython @('scripts\build_windows_models.py','--archive',$modelSource,'--destination',$engines,'--cmake',$cmake) }
$runtime = Join-Path $BuildDirectory 'runtime'
if (-not (Test-Path (Join-Path $runtime 'asr\receipt.json'))) { Checked-Run $buildPython @('scripts\build_windows_runtime.py','--destination',$runtime,'--cache',$cache,'--vcpkg',(Join-Path $BuildDirectory 'vcpkg'),'--cmake',$cmake) }
if (-not (Test-Path (Join-Path $source 'frontend\dist\index.html'))) { throw 'Build frontend with npm run build before packaging, or use the prepared source snapshot containing frontend/dist.' }
$app = Join-Path $BuildDirectory 'Solasi'
Checked-Run $buildPython @('scripts\freeze_windows_app.py','--runtime-dir',$runtime,'--model-engines',$engines,'--destination',$app)
Write-Output ('Windows app: ' + (Join-Path $app 'Solasi.exe'))
Write-Output 'Models and user records were not included. Use a new test vault for acceptance.'
