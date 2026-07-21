# ============================================================
# WeChatDataAnalysis 项目启动脚本 (PowerShell)
# ============================================================
# 使用方法:
#   .\start.ps1                    # 交互式选择群聊
#   .\start.ps1 -List              # 列出所有群聊
#   .\start.ps1 -Group "群名称"    # 监控指定群聊
#   .\start.ps1 -Help              # 显示帮助
# ============================================================

param(
    [switch]$Help,
    [switch]$List,
    [string]$Group = "",
    [int]$Interval = 1,
    [int]$History = 0,
    [switch]$Debug,
    [switch]$Decrypt
)

# 项目根目录
$ProjectRoot = $PSScriptRoot

# 显示Banner
function Show-Banner {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  WeChat Group Monitor - 微信群消息监听系统" -ForegroundColor Yellow
    Write-Host "  Version: 1.0.0" -ForegroundColor Gray
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
}

# 显示帮助
function Show-Help {
    Show-Banner
    Write-Host "使用方法:" -ForegroundColor Green
    Write-Host ""
    Write-Host "  .\start.ps1                    # 交互式选择群聊"
    Write-Host "  .\start.ps1 -List              # 列出所有群聊"
    Write-Host "  .\start.ps1 -Group '群名称'    # 监控指定群聊"
    Write-Host "  .\start.ps1 -Group '群名称' -Interval 2    # 2秒轮询间隔"
    Write-Host "  .\start.ps1 -Group '群名称' -History 100   # 获取100条历史消息"
    Write-Host "  .\start.ps1 -Decrypt           # 解密数据库"
    Write-Host "  .\start.ps1 -Debug             # 调试模式"
    Write-Host ""
    Write-Host "参数说明:" -ForegroundColor Green
    Write-Host "  -Help          显示此帮助信息"
    Write-Host "  -List          列出所有群聊"
    Write-Host "  -Group         指定要监控的群名称"
    Write-Host "  -Interval      轮询间隔（秒），默认1秒"
    Write-Host "  -History       获取历史消息数量"
    Write-Host "  -Decrypt       解密数据库"
    Write-Host "  -Debug         启用调试模式"
    Write-Host ""
    Write-Host "示例:" -ForegroundColor Green
    Write-Host "  .\start.ps1 -List"
    Write-Host "  .\start.ps1 -Group 'AI测试群'"
    Write-Host "  .\start.ps1 -Group 'AI测试群' -History 50 -Interval 2"
    Write-Host ""
}

# 检查Python环境
function Check-Python {
    $pythonCmd = $null
    
    # 尝试 python3
    if (Get-Command python3 -ErrorAction SilentlyContinue) {
        $pythonCmd = "python3"
    }
    # 尝试 python
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $pythonCmd = "python"
    }
    
    if (-not $pythonCmd) {
        Write-Host "[错误] 未找到 Python，请先安装 Python 3.11+" -ForegroundColor Red
        exit 1
    }
    
    # 检查版本
    $version = & $pythonCmd --version 2>&1
    Write-Host "[信息] Python 版本: $version" -ForegroundColor Gray
    
    return $pythonCmd
}

# 检查微信进程
function Check-WeChat {
    $wechat = Get-Process -Name "WeChat", "Weixin" -ErrorAction SilentlyContinue
    
    if (-not $wechat) {
        Write-Host "[警告] 未检测到微信进程，请先启动微信并登录" -ForegroundColor Yellow
        Write-Host "[提示] 等待微信启动..." -ForegroundColor Gray
        
        # 等待30秒
        $waited = 0
        while ($waited -lt 30) {
            Start-Sleep -Seconds 1
            $wechat = Get-Process -Name "WeChat", "Weixin" -ErrorAction SilentlyContinue
            if ($wechat) {
                Write-Host "[信息] 检测到微信进程" -ForegroundColor Green
                return $true
            }
            $waited++
            Write-Host "." -NoNewline -ForegroundColor Gray
        }
        
        Write-Host ""
        Write-Host "[错误] 超时：请手动启动微信并登录后重试" -ForegroundColor Red
        return $false
    }
    
    Write-Host "[信息] 检测到微信进程: PID=$($wechat.Id)" -ForegroundColor Green
    return $true
}

# 主函数
function Main {
    Show-Banner
    
    # 显示帮助
    if ($Help) {
        Show-Help
        exit 0
    }
    
    # 检查Python
    $pythonCmd = Check-Python
    
    # 检查微信进程
    if (-not (Check-WeChat)) {
        exit 1
    }
    
    # 切换到项目目录
    Set-Location $ProjectRoot
    
    # 构建命令参数
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
    
    # 如果是解密模式，使用 tn_combined_v3.py
    if ($Decrypt) {
        $script = "src\tn_combined_v3.py"
        $args = @("-d")
    }
    
    # 显示执行命令
    Write-Host "[执行] $pythonCmd $script $args" -ForegroundColor Gray
    Write-Host ""
    
    # 执行脚本
    try {
        & $pythonCmd $script @args
    }
    catch {
        Write-Host "[错误] 执行失败: $_" -ForegroundColor Red
        exit 1
    }
}

# 运行主函数
Main