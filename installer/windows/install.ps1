<#
    installer — Windows bootstrap (PowerShell + Winget).

    Bootstraps Python via Winget, then hands off to the cross-platform
    installer for the rest (packages, config, global commands, verification).

    Usage:
        powershell -ExecutionPolicy Bypass -File install.ps1 [--non-interactive]

    Notes:
      * Requires Windows 10 1809+ with the App Installer (winget) available.
      * Run from a normal (non-admin) terminal; Winget installs to the user
        scope and the installer avoids elevation wherever possible.
      * Installer commands afterwards: `installer install`, `installer doctor`
        `installer verify`, `installer update`, `installer uninstall`.
#>
[CmdletBinding()]
param(
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.ForegroundColor = "Cyan"
Write-Host "`n╔═══════════════════════════════════════════════════╗"
Write-Host "║   YT-AUTO BOOTSTRAP INSTALLER  (Windows)          ║"
Write-Host "╚═══════════════════════════════════════════════════╝`n"
$Host.UI.RawUI.ForegroundColor = "White"

function Test-Command($Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# --- 1. Winget -----------------------------------------------------------
if (-not (Test-Command winget)) {
    Write-Host "✗ winget not found. Install the App Installer from the Microsoft Store:" -ForegroundColor Red
    Write-Host "  https://apps.microsoft.com/detail/9nblggh4nns1"
    exit 1
}
Write-Host "✓ Detecting OS   -> Windows (winget)"

# --- 2. Python -----------------------------------------------------------
if (Test-Command python) {
    $pyVer = (python --version 2>&1)
    Write-Host "✓ Python         -> $pyVer"
} else {
    Write-Host "Installing Python via winget..."
    winget install --id Python.Python.3.12 --exact --scope user `
        --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
    if (-not (Test-Command python)) {
        Write-Host "✗ Python install did not land on PATH. Reopen your terminal and retry." -ForegroundColor Red
        exit 1
    }
    Write-Host "✓ Python         -> $(python --version 2>&1)"
}

# --- 3. Repo checkout ----------------------------------------------------
$base = Join-Path $env:LOCALAPPDATA "yt-auto"
$src  = Join-Path $base "installer"
if (Test-Path $src) {
    Write-Host "✓ Source         -> using existing copy"
} else {
    Write-Host "Cloning installer source..."
    if (Test-Command git) {
        git clone --depth 1 https://github.com/adittaya/workflow-youtube.git $base 2>$null
    } else {
        $zip = Join-Path $base "repo.zip"
        New-Item -ItemType Directory -Force -Path $base | Out-Null
        Invoke-WebRequest -Uri "https://github.com/adittaya/workflow-youtube/archive/refs/heads/main.zip" -OutFile $zip
        Expand-Archive -Path $zip -DestinationPath $base -Force
        Move-Item (Join-Path $base "workflow-youtube-main\*") $base -Force
        Remove-Item $zip, (Join-Path $base "workflow-youtube-main") -Recurse -Force
    }
}
Write-Host "✓ Source         -> $src"

# --- 4. Hand off to the Python installer --------------------------------
$flag = @()
if ($NonInteractive) { $flag = @("--non-interactive") }
python (Join-Path $src "__main__.py") install @flag
exit $LASTEXITCODE
