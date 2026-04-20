# Yfine one-shot installer for Windows 10/11.
# Installs entirely in the user profile - NO admin privileges required.
# Usage (PowerShell):
#   irm https://raw.githubusercontent.com/AlexDevFlow/Yfine/main/scripts/install-windows.ps1 | iex
#
# If PowerShell blocks execution, launch once with:
#   powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/AlexDevFlow/Yfine/main/scripts/install-windows.ps1 | iex"

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

$AppName    = 'Yfine'
$AppId      = 'yfine'
$RepoSlug   = 'AlexDevFlow/Yfine'
$InstallDir = Join-Path $env:LOCALAPPDATA $AppName
$StartMenu  = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$DesktopDir = [Environment]::GetFolderPath('Desktop')
$ShortcutName = "$AppName.lnk"
$PyVer      = '3.11'

function Cyan($msg)  { Write-Host $msg -ForegroundColor Cyan }
function Green($msg) { Write-Host $msg -ForegroundColor Green }
function Red($msg)   { Write-Host $msg -ForegroundColor Red }

Cyan "== Yfine installer for Windows (nessun admin richiesto) =="

# 1) uv (Astral) - portable Python manager
$uvLocal = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
if (-not (Get-Command uv -ErrorAction SilentlyContinue) -and -not (Test-Path $uvLocal)) {
    Cyan "Installo uv (gestore Python portabile)..."
    Invoke-Expression (Invoke-RestMethod 'https://astral.sh/uv/install.ps1')
}
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Red "uv non è finito nel PATH. Apri un nuovo PowerShell e rilancia lo script."
    exit 1
}

# 2) Python
Cyan "Installo Python $PyVer..."
uv python install $PyVer

# 3) Scarica il codice come zip (Expand-Archive nativo, no dipendenze extra)
if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null }
$tmpdir = Join-Path $env:TEMP "yfine-install-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $tmpdir -Force | Out-Null
try {
    Cyan "Scarico Yfine..."
    $zipPath = Join-Path $tmpdir 'yfine.zip'
    Invoke-WebRequest -Uri "https://codeload.github.com/$RepoSlug/zip/refs/heads/main" -OutFile $zipPath -UseBasicParsing
    Expand-Archive -Path $zipPath -DestinationPath $tmpdir -Force
    $srcDir = Get-ChildItem -Path $tmpdir -Directory | Where-Object { $_.Name -like 'Yfine-*' } | Select-Object -First 1
    if (-not $srcDir) { Red "Estrazione fallita"; exit 1 }

    Cyan "Copio / aggiorno i file in $InstallDir (dati utente preservati)..."
    # robocopy: /MIR-like but preserving user data; exclude .venv, *.db, *.log
    & robocopy $srcDir.FullName $InstallDir /E /XD .venv /XF *.db *.log /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    # robocopy uses non-zero exit codes as "success with info" — reset so $ErrorActionPreference doesn't trip us
    $global:LASTEXITCODE = 0
} finally {
    Remove-Item -Recurse -Force $tmpdir -ErrorAction SilentlyContinue
}

Set-Location $InstallDir

# 4) Venv
Cyan "Creo l'ambiente virtuale Python..."
uv venv --python $PyVer .venv

# 5) Dipendenze (Windows: Qt backend come su Linux — requirements completo)
Cyan "Installo le librerie Python (prima volta ~2-3 minuti)..."
$env:VIRTUAL_ENV = (Join-Path $InstallDir '.venv')
uv pip install -r requirements.txt

# 6) Converti icon.png -> icon.ico con Pillow (installato come dipendenza di reportlab)
$pyExe  = Join-Path $InstallDir '.venv\Scripts\python.exe'
$pngIco = Join-Path $InstallDir 'static\icon.png'
$icoPath = Join-Path $InstallDir 'static\icon.ico'
if ((Test-Path $pngIco) -and -not (Test-Path $icoPath)) {
    $convertScript = @"
from PIL import Image
img = Image.open(r'$pngIco')
img.save(r'$icoPath', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
"@
    & $pyExe -c $convertScript 2>$null | Out-Null
}

# 7) Shortcut .lnk in Start Menu e sul Desktop
$wshShell = New-Object -ComObject WScript.Shell
$pythonw  = Join-Path $InstallDir '.venv\Scripts\pythonw.exe'
foreach ($dir in @($StartMenu, $DesktopDir)) {
    if (-not (Test-Path $dir)) { continue }
    $lnkPath = Join-Path $dir $ShortcutName
    $shortcut = $wshShell.CreateShortcut($lnkPath)
    $shortcut.TargetPath       = $pythonw
    $shortcut.Arguments        = 'desktop.py'
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.Description      = 'Personal finance app - runs locally on your machine'
    if (Test-Path $icoPath) { $shortcut.IconLocation = $icoPath }
    $shortcut.Save()
}

Green "== Installazione completata =="
Write-Host "Yfine è nel Menu Start. Lo trovi anche sul Desktop."
Write-Host "Avvio Yfine per la prima volta..."
Start-Process -FilePath $pythonw -ArgumentList 'desktop.py' -WorkingDirectory $InstallDir
