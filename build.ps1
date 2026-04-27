# Build wispr-clone as a windowed Windows .exe via PyInstaller.
#
# Run from PowerShell (NOT WSL) with the project's Windows venv activated:
#
#     cd E:\all_repo\wispr_clone
#     .\.venv\Scripts\Activate.ps1
#     .\build.ps1
#
# Output: dist\wispr-clone\wispr-clone.exe (one-folder bundle).
# Use one-folder over one-file: faster startup, easier antivirus
# whitelisting, and the .exe path is stable for a Startup-folder shortcut.

$ErrorActionPreference = "Stop"

# Ensure we are on Windows-native Python, not a WSL Linux interpreter.
$pyExe = & python -c "import sys; print(sys.executable)"
if ($pyExe -notmatch '^[A-Za-z]:\\') {
    Write-Error "Active Python is not Windows-native: $pyExe`nActivate the project's Windows venv before running this script."
    exit 1
}
Write-Host "Using Python: $pyExe"

# Clean previous build artifacts so stale files don't shadow new ones.
if (Test-Path "build")  { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist")   { Remove-Item -Recurse -Force "dist" }
Get-ChildItem -Filter "*.spec" | Remove-Item -Force -ErrorAction SilentlyContinue

# Use the root-level launcher as the entry. It does
#   from wispr_clone.main import main
# (absolute import) which avoids PyInstaller's "relative import with no known
# parent package" trap that fires when src\wispr_clone\main.py is treated as
# a top-level script. --paths src tells PyInstaller where to find the package.
$entry = "main.py"
if (-not (Test-Path $entry)) {
    Write-Error "Entry script not found: $entry"
    exit 1
}

$pyiArgs = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "wispr-clone",
    "--paths", "src",
    "--add-data", "assets;assets",
    "--hidden-import", "PIL._tkinter_finder",
    "--hidden-import", "tkinter",
    "--collect-submodules", "wispr_clone",
    $entry
)

Write-Host "Running: pyinstaller $($pyiArgs -join ' ')"
& python -m PyInstaller @pyiArgs

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller exited with code $LASTEXITCODE"
    exit $LASTEXITCODE
}

$exe = "dist\wispr-clone\wispr-clone.exe"
if (Test-Path $exe) {
    Write-Host ""
    Write-Host "Build OK -> $exe"
    Write-Host "Run it directly to verify the tray icon appears and the hotkey works."
    Write-Host "User data lives in `$env:APPDATA\wispr-clone\ (config.toml, dictionary.txt, .env, log)."
} else {
    Write-Error "Build finished but $exe is missing."
    exit 1
}
