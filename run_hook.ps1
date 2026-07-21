# ============================================================
# WeChatDataAnalysis HOOK Key Acquisition Script (PowerShell)
# ============================================================
# Usage:
#   Run as Administrator
#   Then start WeChat and login, key will be auto-captured
# ============================================================

param(
    [switch]$Help,
    [int]$Timeout = 120
)

# Check Admin privileges
function Test-Admin {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    Write-Host "[ERROR] This script requires Administrator privileges" -ForegroundColor Red
    Write-Host "[TIP] Right-click PowerShell and select 'Run as Administrator'" -ForegroundColor Yellow
    exit 1
}

# Display Banner
function Show-Banner {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  WeChat HOOK Key Acquisition Tool" -ForegroundColor Yellow
    Write-Host "  Version: 1.0.0" -ForegroundColor Gray
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
}

# Display help
if ($Help) {
    Show-Banner
    Write-Host "Usage:" -ForegroundColor Green
    Write-Host ""
    Write-Host "  .\run_hook.ps1              # Start HOOK listener, wait for WeChat login"
    Write-Host "  .\run_hook.ps1 -Timeout 180 # Set timeout to 180 seconds"
    Write-Host ""
    Write-Host "Notes:" -ForegroundColor Green
    Write-Host "  1. This script requires Administrator privileges"
    Write-Host "  2. After running, start WeChat and login"
    Write-Host "  3. Key will be saved to output/account_keys.json after login"
    Write-Host ""
    exit 0
}

Show-Banner

# Project root directory
$ProjectRoot = $PSScriptRoot
$SrcDir = Join-Path $ProjectRoot "src"

Write-Host "[INFO] Project directory: $ProjectRoot" -ForegroundColor Gray

# Check Python
$pythonCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $pythonCmd = "python3"
}

if (-not $pythonCmd) {
    Write-Host "[ERROR] Python not found, please install Python 3.11+" -ForegroundColor Red
    exit 1
}

$version = & $pythonCmd --version 2>&1
Write-Host "[INFO] Python version: $version" -ForegroundColor Gray

# Check WeChat process
Write-Host ""
Write-Host "[STEP1] Checking WeChat process..." -ForegroundColor Cyan

$wechat = Get-Process -Name "WeChat", "Weixin" -ErrorAction SilentlyContinue
if ($wechat) {
    Write-Host "[INFO] WeChat is running: PID=$($wechat.Id)" -ForegroundColor Green
    Write-Host "[WARN] wx_key Hook requires WeChat to restart" -ForegroundColor Yellow
    Write-Host ""
    
    $confirm = Read-Host "Kill WeChat and restart for Hook? (y/n)"
    if ($confirm -eq 'y') {
        Write-Host "[INFO] Killing WeChat processes..." -ForegroundColor Gray
        Stop-Process -Name "WeChat", "Weixin" -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Write-Host "[INFO] WeChat processes killed." -ForegroundColor Green
    } else {
        Write-Host "[INFO] Hook requires WeChat restart. Exiting..." -ForegroundColor Gray
        exit 0
    }
} else {
    Write-Host "[INFO] WeChat not running" -ForegroundColor Gray
}

# Detect WeChat installation path
Write-Host ""
Write-Host "[STEP1.5] Detecting WeChat installation..." -ForegroundColor Cyan

$wechatPaths = @(
    "C:\Program Files\Tencent\Weixin\Weixin.exe",
    "C:\Program Files\Tencent\WeChat\WeChat.exe",
    "C:\Program Files (x86)\Tencent\Weixin\Weixin.exe",
    "C:\Program Files (x86)\Tencent\WeChat\WeChat.exe",
    "${env:LOCALAPPDATA}\Tencent\Weixin\Weixin.exe"
)

$wechatExe = $null
foreach ($path in $wechatPaths) {
    if (Test-Path $path) {
        $wechatExe = $path
        break
    }
}

if (-not $wechatExe) {
    # Try registry
    try {
        $regPath = Get-ItemProperty "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like "*微信*" -or $_.DisplayName -like "*WeChat*" }
        if ($regPath) {
            $installDir = $regPath.InstallLocation
            if ($installDir) {
                $candidate = Join-Path $installDir "Weixin.exe"
                if (Test-Path $candidate) {
                    $wechatExe = $candidate
                }
            }
        }
    } catch {}
}

if ($wechatExe) {
    Write-Host "[INFO] Found WeChat: $wechatExe" -ForegroundColor Green
} else {
    Write-Host "[WARN] WeChat installation not found, will wait for manual start" -ForegroundColor Yellow
}

# Create temp Python script for HOOK - 使用 WeChatKeyFetcher（已验证成功的方法）
$hookScript = @"
import sys
import os
from pathlib import Path

# Add project path
sys.path.insert(0, str(Path(__file__).parent / "src"))

try:
    from wechat_decrypt_tool.key_service import WeChatKeyFetcher
    from wechat_decrypt_tool.wechat_detection import detect_current_logged_in_account
    from wechat_decrypt_tool.key_store import upsert_account_keys_in_store
except ImportError as e:
    print(f"[HOOK] Import error: {e}")
    sys.exit(1)

def main():
    print("[HOOK] Starting WeChat key listener (WeChatKeyFetcher mode)...")
    
    # Get WeChat exe path from argument
    wechat_exe = sys.argv[2] if len(sys.argv) > 2 else None
    
    # Detect current account
    print("[HOOK] Detecting current logged in account...")
    try:
        result = detect_current_logged_in_account()
        account_id = result.get('current_account') if result else None
    except Exception as e:
        print(f"[HOOK] Account detection error: {e}")
        account_id = None
    
    # Create key fetcher
    fetcher = WeChatKeyFetcher()
    
    print("[HOOK] WeChat will be killed and restarted...")
    print("[HOOK] Please login within 60 seconds after WeChat starts")
    print("")
    
    try:
        # Use WeChatKeyFetcher to get key (this will kill & restart WeChat)
        result = fetcher.fetch_db_key(wechat_install_path=wechat_exe)
        
        if result and result.get('db_key'):
            key = result['db_key']
            print(f"[HOOK] Key acquired: {key[:16]}...")
            
            # Save key
            if account_id:
                upsert_account_keys_in_store(account_id, db_key=key)
                print(f"[HOOK] Key saved to output/account_keys.json for account: {account_id}")
            else:
                # Try to get account from result
                print("[HOOK] Key acquired but no account ID detected")
                print(f"[HOOK] Key: {key}")
        else:
            print("[HOOK] Failed to get key: result is empty")
            
    except TimeoutError as e:
        print(f"[HOOK] Timeout: {e}")
        print("[HOOK] Please ensure you login within 60 seconds")
    except RuntimeError as e:
        print(f"[HOOK] Error: {e}")
        print("[HOOK] Please ensure:")
        print("  1. Running with Administrator privileges")
        print("  2. WeChat is installed correctly")
    except Exception as e:
        print(f"[HOOK] Unexpected error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
"@

# Save temp script
$tempScriptPath = Join-Path $ProjectRoot "temp_hook_runner.py"
$hookScript | Out-File -FilePath $tempScriptPath -Encoding UTF8

Write-Host ""
Write-Host "[STEP2] Starting HOOK listener..." -ForegroundColor Cyan
Write-Host "[INFO] WeChat will be auto-started. Please login within $Timeout seconds" -ForegroundColor Yellow
Write-Host ""

try {
    # Execute HOOK script with WeChat path
    if ($wechatExe) {
        & $pythonCmd $tempScriptPath $Timeout $wechatExe
    } else {
        & $pythonCmd $tempScriptPath $Timeout
    }
    
} catch {
    Write-Host "[ERROR] Execution failed: $_" -ForegroundColor Red
} finally {
    # Cleanup temp file
    if (Test-Path $tempScriptPath) {
        Remove-Item $tempScriptPath -Force
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  HOOK Acquisition Complete" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan