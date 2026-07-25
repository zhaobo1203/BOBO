@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo ========================================
echo  微信群消息监听与股票分析系统 - 打包脚本 v3.0.0
echo  模块1(微信监控) + 模块2(A股数据) + 模块3(股票分析)
echo ========================================
echo.

REM 获取脚本所在目录
cd /d "%~dp0"

REM 记录开始时间
set START_TIME=%time%

REM ============== 步骤1: 检查环境 ==============
echo [1/7] 检查环境...

REM 检查Python环境
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python环境，请先安装Python 3.11+
    goto :error_exit
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo       Python 版本: %PY_VER%

REM 检查PyInstaller
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [信息] 正在安装PyInstaller...
    pip install pyinstaller -q
)
echo       PyInstaller: OK

REM 检查spec文件
if not exist "release_v3.spec" (
    echo [错误] 未找到 release_v3.spec 文件
    goto :error_exit
)
echo       Spec 文件: OK

REM 检查入口文件
if not exist "src\main.py" (
    echo [错误] 未找到 src\main.py 入口文件
    goto :error_exit
)
echo       入口文件: OK

echo.

REM ============== 步骤2: 清理旧构建 ==============
echo [2/7] 清理旧构建文件...

if exist "build" (
    rmdir /s /q "build" 2>nul
    echo       已删除 build 目录
)

if exist "dist" (
    rmdir /s /q "dist" 2>nul
    echo       已删除 dist 目录
)

if exist "__pycache__" (
    rmdir /s /q "__pycache__" 2>nul
)

echo       清理完成
echo.

REM ============== 步骤3: 检查A股数据库 ==============
echo [3/7] 检查A股数据库...

if exist "data\a_stock_db\a_stock.db" (
    for %%I in ("data\a_stock_db\a_stock.db") do set DB_SIZE=%%~zI
    set /a DB_SIZE_KB=!DB_SIZE! / 1024
    echo       A股数据库: OK (!DB_SIZE_KB! KB)
) else (
    echo [警告] A股数据库不存在: data\a_stock_db\a_stock.db
    echo       打包后A股数据更新功能将不可用
)

echo.

REM ============== 步骤4: 执行PyInstaller打包 ==============
echo [4/7] 执行PyInstaller打包...
echo       这可能需要较长时间（含三模块+数据），请耐心等待...
echo.

python -m PyInstaller release_v3.spec --noconfirm

if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请检查错误信息
    goto :error_exit
)

echo.
echo       打包完成
echo.

REM ============== 步骤5: 验证输出 ==============
echo [5/7] 验证输出文件...

set EXE_FILE=dist\微信群消息监听_v3.0.0.exe

if not exist "%EXE_FILE%" (
    echo [错误] 未生成EXE文件: %EXE_FILE%
    goto :error_exit
)

echo       EXE 文件已生成: %EXE_FILE%

REM 获取文件大小
for %%I in ("%EXE_FILE%") do set EXE_SIZE=%%~zI
set /a EXE_SIZE_MB=%EXE_SIZE% / 1048576
echo       文件大小: %EXE_SIZE_MB% MB (%EXE_SIZE% 字节)

if %EXE_SIZE_MB% LSS 50 (
    echo [警告] EXE文件小于50MB，可能打包不完整
)

echo.

REM ============== 步骤6: 准备发布文件 ==============
echo [6/7] 准备发布文件...

REM 创建release目录
if not exist "release" mkdir release

REM 复制EXE文件
copy /y "%EXE_FILE%" "release\" >nul 2>&1
echo       已复制 EXE 到 release\

REM 复制VC++运行时（如果存在）
if exist "vc_redist.x64.exe" (
    copy /y "vc_redist.x64.exe" "release\" >nul 2>&1
    echo       已复制 vc_redist.x64.exe
) else (
    echo [警告] 未找到 vc_redist.x64.exe
)

REM 生成使用说明.txt
echo 微信群消息监听与股票分析系统 v3.0.0 > release\使用说明.txt
echo. >> release\使用说明.txt
echo 【功能说明】 >> release\使用说明.txt
echo 1. 微信群消息实时监控（模块1） >> release\使用说明.txt
echo 2. A股数据库管理，支持手动更新（模块2） >> release\使用说明.txt
echo 3. 股票提及自动匹配与统计分析（模块3） >> release\使用说明.txt
echo. >> release\使用说明.txt
echo 【使用方法】 >> release\使用说明.txt
echo 1. 确保已安装微信并登录 >> release\使用说明.txt
echo 2. 首次运行请先安装 vc_redist.x64.exe >> release\使用说明.txt
echo 3. 双击运行 微信群消息监听_v3.0.0.exe >> release\使用说明.txt
echo 4. 按照提示完成：进程检测→密钥获取→选择群聊 >> release\使用说明.txt
echo 5. 监控启动后，股票分析服务自动运行 >> release\使用说明.txt
echo. >> release\使用说明.txt
echo 【API服务】 >> release\使用说明.txt
echo - 地址: http://localhost:8000 >> release\使用说明.txt
echo - 健康检查: GET /api/health >> release\使用说明.txt
echo - 手动刷新: POST /api/refresh >> release\使用说明.txt
echo - 增量刷新: POST /api/incremental-refresh >> release\使用说明.txt
echo - 更新A股数据库: POST /api/update-stock-db >> release\使用说明.txt
echo - 日统计: GET /api/stats/daily >> release\使用说明.txt
echo - 周统计: GET /api/stats/weekly >> release\使用说明.txt
echo - 月统计: GET /api/stats/monthly >> release\使用说明.txt
echo. >> release\使用说明.txt
echo 【数据目录】 >> release\使用说明.txt
echo - A股数据库: data/a_stock_db/a_stock.db >> release\使用说明.txt
echo - 消息数据库: data/messages.db >> release\使用说明.txt
echo - 匹配结果: data/stock_mentions.db >> release\使用说明.txt
echo - 日志文件: logs/ >> release\使用说明.txt
echo - 密钥存储: output/account_keys.json >> release\使用说明.txt
echo. >> release\使用说明.txt
echo 【注意事项】 >> release\使用说明.txt
echo - 首次运行需要获取数据库密钥（可能需要重启微信） >> release\使用说明.txt
echo - A股数据库已内嵌，首次运行自动释放 >> release\使用说明.txt
echo - 可通过API手动更新A股数据库 >> release\使用说明.txt
echo - 如遇DLL缺失问题，请安装 vc_redist.x64.exe >> release\使用说明.txt

echo       已生成 使用说明.txt

echo.

REM ============== 步骤7: 完成 ==============
echo [7/7] 打包完成!
echo.

echo ========================================
echo  打包成功!
echo ========================================
echo.
echo  输出文件: %EXE_FILE%
echo  文件大小: %EXE_SIZE_MB% MB
echo  发布目录: release\
echo.
echo  发布文件清单:
echo    - 微信群消息监听_v3.0.0.exe
echo    - vc_redist.x64.exe
echo    - 使用说明.txt
echo.
echo ========================================
echo.

pause
exit /b 0

:error_exit
echo.
echo ========================================
echo  打包失败!
echo ========================================
echo.
echo  请检查错误信息并修复后重试
echo.
pause
exit /b 1