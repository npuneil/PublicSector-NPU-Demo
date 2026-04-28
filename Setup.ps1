# Public Sector Hybrid AI Demo - Setup Script
Write-Host ""
Write-Host "==============================================================" -ForegroundColor Blue
Write-Host "   Public Sector Hybrid AI Demo  SETUP" -ForegroundColor Blue
Write-Host "   Powered by Intel Copilot+ PC + Foundry Local" -ForegroundColor Blue
Write-Host "   On-Device + Cloud Hybrid AI" -ForegroundColor Blue
Write-Host "==============================================================" -ForegroundColor Blue
Write-Host ""

# Check for Intel
try {
    $cpuName = (Get-CimInstance Win32_Processor).Name
    if ($cpuName -match "Intel") {
        Write-Host "[INFO] Intel detected: $cpuName" -ForegroundColor Cyan
    } elseif ($cpuName -match "Qualcomm|Snapdragon") {
        Write-Host "[INFO] Snapdragon detected: $cpuName" -ForegroundColor Cyan
    }
} catch {}

# Resolve Python command
$pythonCmd = $null
foreach ($cmd in @('python', 'py', 'python3')) {
    try {
        $testArgs = if ($cmd -eq 'py') { @('-3', '--version') } else { @('--version') }
        & $cmd @testArgs 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0 -or $?) {
            $pythonCmd = if ($cmd -eq 'py') { 'py -3' } else { $cmd }
            break
        }
    } catch { }
}
if (-not $pythonCmd) {
    Write-Host "[ERROR] Python not found. Install Python 3.10+ from https://python.org" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Python found: $pythonCmd" -ForegroundColor Green

# Check Foundry Local - only install if missing
$foundryOk = $false
try {
    $fv = foundry --version 2>&1
    $foundryOk = ($LASTEXITCODE -eq 0)
} catch {}
if ($foundryOk) {
    Write-Host "[OK] Foundry Local already installed: $fv" -ForegroundColor Green
} else {
    Write-Host "[INFO] Foundry Local not found. Install it with:" -ForegroundColor Yellow
    Write-Host "       winget install Microsoft.FoundryLocal" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "       Then re-run this setup script." -ForegroundColor Yellow
    exit 1
}

# Create venv
if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    Write-Host "[SETUP] Creating virtual environment..." -ForegroundColor Cyan
    Invoke-Expression "$pythonCmd -m venv .venv"
    if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
        Write-Host "[ERROR] Failed to create virtual environment." -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] Virtual environment created." -ForegroundColor Green
} else {
    Write-Host "[OK] Virtual environment exists." -ForegroundColor Green
}

# Install deps
Write-Host "[SETUP] Installing dependencies..." -ForegroundColor Cyan
& .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt --quiet

Write-Host ""
Write-Host "[OK] Setup complete! Run StartApp.bat or: python app.py" -ForegroundColor Green
Write-Host "     Then open http://localhost:5000" -ForegroundColor Green
Write-Host ""