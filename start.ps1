# ============================================================
# WeChatDataAnalysis Project Start Script (PowerShell)
# ============================================================
# Usage:
#   .\start.ps1                    # Interactive group selection
#   .\start.ps1 -All               # Start all services
#   .\start.ps1 -List              # List all groups
#   .\start.ps1 -Group "GroupName" # Monitor specific group
#   .\start.ps1 -Stock             # Start stock analysis only
#   .\start.ps1 -Help              # Show help
# ============================================================

param(
    [switch]$Help,
    [switch]$List,
    [switch]$All,
    [switch]$Stock,
    [string]$Group = "",
    [int]$Interval = 1,
    [int]$History = 0,
    [switch]$Debug,
    [switch]$Decrypt,
    [switch]$Simple,
    [switch]$Test,
    [switch]$TestAll,
    [switch]$TestInteraction,
    [switch]$TestTN
)

# Project root directory
$ProjectRoot = $PSScriptRoot

# Show Banner
function Show-Banner {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  WeChatDataAnalysis - WeChat Group Data Analysis System" -ForegroundColor Yellow
    Write-Host "  Version: 3.0.0" -ForegroundColor Gray
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
}

# Show Help
function Show-Help {
    Show-Banner
    Write-Host "Usage:" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Start Modes:"
    Write-Host "  .\start.ps1                    # Interactive group selection"
    Write-Host "  .\start.ps1 -All               # Start all services (WeChat + Stock)"
    Write-Host "  .\start.ps1 -Simple            # Start simple WeChat monitor"
    Write-Host "  .\start.ps1 -Stock             # Start stock analysis only"
    Write-Host ""
    Write-Host "  Group Management:"
    Write-Host "  .\start.ps1 -List              # List all groups"
    Write-Host "  .\start.ps1 -Group 'GroupName' # Monitor specific group"
    Write-Host "  .\start.ps1 -Group 'GroupName' -Interval 2"
    Write-Host "  .\start.ps1 -Group 'GroupName' -History 100"
    Write-Host ""
    Write-Host "  Module Tests:"
    Write-Host "  .\start.ps1 -TestAll           # Run all module tests"
    Write-Host "  .\start.ps1 -TestInteraction   # Run interaction test"
    Write-Host "  .\start.ps1 -TestTN            # Run TN-01~TN-06 tests"
    Write-Host ""
    Write-Host "  Other Functions:"
    Write-Host "  .\start.ps1 -Decrypt           # Decrypt database"
    Write-Host "  .\start.ps1 -Debug             # Debug mode"
    Write-Host "  .\start.ps1 -Help              # Show this help"
    Write-Host ""
    Write-Host "Parameters:" -ForegroundColor Green
    Write-Host "  -All           Start all services (WeChat monitor + Stock API)"
    Write-Host "  -Simple        Start simple WeChat monitor (simple_monitor.py)"
    Write-Host "  -Stock         Start stock analysis only (port 8000)"
    Write-Host "  -List          List all groups"
    Write-Host "  -Group         Specify group name to monitor"
    Write-Host "  -Interval      Polling interval (seconds), default 1"
    Write-Host "  -History       Number of history messages to fetch"
    Write-Host "  -Decrypt       Decrypt database"
    Write-Host "  -Debug         Enable debug mode"
    Write-Host ""
    Write-Host "Service Ports:" -ForegroundColor Green
    Write-Host "  Stock Analysis API:  http://localhost:8000"
    Write-Host "  API Documentation:   http://localhost:8000/docs"
    Write-Host ""
    Write-Host "Examples:" -ForegroundColor Green
    Write-Host "  .\start.ps1 -All"
    Write-Host "  .\start.ps1 -List"
    Write-Host "  .\start.ps1 -Group 'TestGroup'"
    Write-Host "  .\start.ps1 -Group 'TestGroup' -History 50 -Interval 2"
    Write-Host "  .\start.ps1 -Stock"
    Write-Host ""
}

# Check Python environment
function Check-Python {
    $pythonCmd = $null
    
    # Check venv first
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $pythonCmd = $venvPython
        Write-Host "[INFO] Using venv Python: $venvPython" -ForegroundColor Gray
    }
    # Try python
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $pythonCmd = "python"
    }
    # Try python3
    elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
        $pythonCmd = "python3"
    }
    
    if (-not $pythonCmd) {
        Write-Host "[ERROR] Python not found, please install Python 3.11+" -ForegroundColor Red
        exit 1
    }
    
    # Check version
    $version = & $pythonCmd --version 2>&1
    Write-Host "[INFO] Python version: $version" -ForegroundColor Gray
    
    return $pythonCmd
}

# Check WeChat process
function Check-WeChat {
    $wechat = Get-Process -Name "WeChat", "Weixin" -ErrorAction SilentlyContinue
    
    if (-not $wechat) {
        Write-Host "[WARNING] WeChat process not detected, please start WeChat first" -ForegroundColor Yellow
        Write-Host "[INFO] Waiting for WeChat to start..." -ForegroundColor Gray
        
        # Wait 30 seconds
        $waited = 0
        while ($waited -lt 30) {
            Start-Sleep -Seconds 1
            $wechat = Get-Process -Name "WeChat", "Weixin" -ErrorAction SilentlyContinue
            if ($wechat) {
                Write-Host "[INFO] WeChat process detected" -ForegroundColor Green
                return $true
            }
            $waited++
            Write-Host "." -NoNewline -ForegroundColor Gray
        }
        
        Write-Host ""
        Write-Host "[ERROR] Timeout: Please start WeChat manually and try again" -ForegroundColor Red
        return $false
    }
    
    Write-Host "[INFO] WeChat process detected: PID=$($wechat.Id)" -ForegroundColor Green
    return $true
}

# Start Stock Analysis Service
function Start-StockAnalysis {
    Write-Host "[START] Stock Analysis Service..." -ForegroundColor Green
    
    $port = 8000
    
    # Check if port is in use
    $portInUse = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($portInUse) {
        Write-Host "[WARNING] Port $port is already in use" -ForegroundColor Yellow
        Write-Host "[INFO] Attempting to stop the process..." -ForegroundColor Gray
        $procId = $portInUse.OwningProcess
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
    
    # Start service
    $process = Start-Process -FilePath $pythonCmd `
        -ArgumentList "-m", "uvicorn", "src.stock_analysis.main:app", "--host", "0.0.0.0", "--port", "$port" `
        -PassThru -NoNewWindow
    
    Write-Host "[OK] Stock Analysis Service started (PID: $($process.Id))" -ForegroundColor Green
    Write-Host "[INFO] API URL: http://localhost:$port" -ForegroundColor Cyan
    Write-Host "[INFO] API Docs: http://localhost:$port/docs" -ForegroundColor Cyan
    
    return $process
}

# Main function
function Main {
    Show-Banner
    
    # Show help
    if ($Help) {
        Show-Help
        exit 0
    }
    
    # Check Python
    $pythonCmd = Check-Python
    $global:pythonCmd = $pythonCmd
    
    # Switch to project directory
    Set-Location $ProjectRoot
    
    # Start all services mode
    if ($All) {
        Write-Host "[MODE] Starting all services" -ForegroundColor Green
        Write-Host ""
        
        # Check WeChat process
        if (-not (Check-WeChat)) {
            exit 1
        }
        
        # Run unified start script
        Write-Host "[EXEC] $pythonCmd start_all.py" -ForegroundColor Gray
        Write-Host ""
        
        try {
            & $pythonCmd start_all.py
        }
        catch {
            Write-Host "[ERROR] Execution failed: $_" -ForegroundColor Red
            exit 1
        }
        return
    }
    
    # Start stock analysis only
    if ($Stock) {
        Write-Host "[MODE] Stock analysis only" -ForegroundColor Green
        Write-Host ""
        
        $proc = Start-StockAnalysis
        if ($proc) {
            Write-Host ""
            Write-Host "Press Ctrl+C to stop..." -ForegroundColor Yellow
            
            # Wait for user interrupt
            try {
                Wait-Process -Id $proc.Id
            }
            catch [System.Management.Automation.ActionPreferenceStopException] {
                # Ctrl+C pressed
            }
        }
        return
    }
    
    # Simple WeChat monitor
    if ($Simple) {
        Write-Host "[MODE] Simple WeChat Monitor" -ForegroundColor Green
        Write-Host ""
        
        if (-not (Check-WeChat)) {
            exit 1
        }
        
        $script = "src\simple_monitor.py"
        Write-Host "[EXEC] $pythonCmd $script" -ForegroundColor Gray
        Write-Host ""
        
        try {
            & $pythonCmd $script
        }
        catch {
            Write-Host "[ERROR] Execution failed: $_" -ForegroundColor Red
            exit 1
        }
        return
    }
    
    # Run all module tests
    if ($TestAll) {
        Write-Host "[MODE] Running all module tests" -ForegroundColor Green
        Write-Host ""
        
        $testScripts = @(
            "test_tn_all_final.py",
            "check_interaction_test.py",
            "check_groups.py",
            "check_contact.py",
            "check_msgs.py",
            "check_match.py",
            "check_a_stock.py"
        )
        
        $failed = @()
        $passed = @()
        
        foreach ($testScript in $testScripts) {
            Write-Host "----------------------------------------" -ForegroundColor Gray
            Write-Host "[TEST] Running $testScript" -ForegroundColor Cyan
            
            try {
                & $pythonCmd $testScript
                if ($LASTEXITCODE -eq 0) {
                    $passed += $testScript
                    Write-Host "[PASS] $testScript" -ForegroundColor Green
                } else {
                    $failed += $testScript
                    Write-Host "[FAIL] $testScript" -ForegroundColor Red
                }
            }
            catch {
                $failed += $testScript
                Write-Host "[FAIL] $testScript : $_" -ForegroundColor Red
            }
            Write-Host ""
        }
        
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host "Test Results:" -ForegroundColor Yellow
        Write-Host "  Passed: $($passed.Count)" -ForegroundColor Green
        Write-Host "  Failed: $($failed.Count)" -ForegroundColor Red
        if ($failed.Count -gt 0) {
            Write-Host "  Failed tests:" -ForegroundColor Red
            foreach ($f in $failed) {
                Write-Host "    - $f" -ForegroundColor Red
            }
        }
        Write-Host "========================================" -ForegroundColor Cyan
        return
    }
    
    # Run interaction test
    if ($TestInteraction) {
        Write-Host "[MODE] Running interaction test" -ForegroundColor Green
        Write-Host ""
        
        Write-Host "[STEP 1] Insert test data..." -ForegroundColor Cyan
        & $pythonCmd insert_interaction_test_data.py
        Write-Host ""
        
        Write-Host "[STEP 2] Verify test data..." -ForegroundColor Cyan
        & $pythonCmd check_interaction_test.py
        Write-Host ""
        
        Write-Host "[DONE] Interaction test completed" -ForegroundColor Green
        return
    }
    
    # Run TN-01~TN-06 tests
    if ($TestTN) {
        Write-Host "[MODE] Running TN-01~TN-06 tests" -ForegroundColor Green
        Write-Host ""
        
        Write-Host "[EXEC] $pythonCmd test_tn_all_final.py" -ForegroundColor Gray
        Write-Host ""
        
        try {
            & $pythonCmd test_tn_all_final.py
        }
        catch {
            Write-Host "[ERROR] Execution failed: $_" -ForegroundColor Red
            exit 1
        }
        return
    }
    
    # Check WeChat process (for group monitor mode)
    if (-not (Check-WeChat)) {
        exit 1
    }
    
    # Build command arguments
    $script = "monitor_group.py"
    $args = @()
    
    if ($List) {
        $args += "--list"
    }
    
    if ($Group) {
        $args += "-g"
        $args += $Group
    }
    
    if ($Interval -gt 0) {
        $args += "-i"
        $args += $Interval
    }
    
    if ($History -gt 0) {
        $args += "--history"
        $args += $History
    }
    
    if ($Debug) {
        $args += "--debug"
    }
    
    # Decrypt mode uses tn_combined_v3.py
    if ($Decrypt) {
        $script = "src\tn_combined_v3.py"
        $args = @("-d")
    }
    
    # Show execution command
    Write-Host "[EXEC] $pythonCmd $script $args" -ForegroundColor Gray
    Write-Host ""
    
    # Execute script
    try {
        & $pythonCmd $script @args
    }
    catch {
        Write-Host "[ERROR] Execution failed: $_" -ForegroundColor Red
        exit 1
    }
}

# Run main function
Main