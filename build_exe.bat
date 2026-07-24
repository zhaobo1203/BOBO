@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo ========================================
echo  微信群消息监听系统 - 打包脚本 v2.0.0
echo ========================================
echo.

REM 获取脚本所在目录
cd /d "%~dp0"

REM 记录开始时间
set START_TIME=%time%

REM ============== 步骤1: 检查环境 ==============
echo [1/6] 检查环境...

REM 检查Python环境
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python环境，请先安装Python 3.11+
    goto :error_exit
)
echo       Python 环境: OK

REM 检查PyInstaller
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [信息] 正在安装PyInstaller...
    pip install pyinstaller -q
)
echo       PyInstaller: OK

REM 检查spec文件
if not exist "simple_monitor.spec" (
    echo [错误] 未找到 simple_monitor.spec 文件
    goto :error_exit
)
echo       Spec 文件: OK

echo.

REM ============== 步骤2: 清理旧构建 ==============
echo [2/6] 清理旧构建文件...

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

REM ============== 步骤3: 执行打包 ==============
echo [3/6] 执行PyInstaller打包...
echo       这可能需要几分钟，请耐心等待...
echo.

python -m PyInstaller simple_monitor.spec --noconfirm

if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请检查错误信息
    goto :error_exit
)

echo.
echo       打包完成
echo.

REM ============== 步骤4: 验证输出 ==============
echo [4/6] 验证输出文件...

set EXE_FILE=dist\微信群消息监听_v2.0.0.exe

if not exist "%EXE_FILE%" (
    echo [错误] 未生成EXE文件: %EXE_FILE%
    goto :error_exit
)

echo       EXE 文件已生成: %EXE_FILE%

REM 获取文件大小
for %%I in ("%EXE_FILE%") do set EXE_SIZE=%%~zI
set /a EXE_SIZE_MB=%EXE_SIZE% / 1048576
echo       文件大小: %EXE_SIZE_MB% MB (%EXE_SIZE% 字节)

echo.

REM ============== 步骤5: 创建发布目录 ==============
echo [5/6] 准备发布文件...

REM 创建release目录（可选，用于分发）
if not exist "release" mkdir release

REM 复制EXE文件
copy /y "%EXE_FILE%" "release\" >nul 2>&1

REM 复制配置文件模板（如果存在）
if exist "key_store.json" (
    copy /y "key_store.json" "release\" >nul 2>&1
    echo       已复制 key_store.json
)

REM 复制VC++运行时（如果存在）
if exist "vc_redist.x64.exe" (
    copy /y "vc_redist.x64.exe" "release\" >nul 2>&1
    echo       已复制 vc_redist.x64.exe
)

REM 创建使用说明
echo 微信群消息监听系统 v2.0.0 > release\使用说明.txt
echo. >> release\使用说明.txt
echo 使用方法: >> release\使用说明.txt
echo 1. 确保已安装微信并登录 >> release\使用说明.txt
echo 2. 双击运行 微信群消息监听.exe >> release\使用说明.txt
echo 3. 按照提示选择要监控的群聊 >> release\使用说明.txt
echo. >> release\使用说明.txt
echo 注意: 首次使用需要获取数据库密钥 >> release\使用说明.txt
echo. >> release\使用说明.txt
echo 如遇DLL缺失问题，请安装 VC++ 运行时: vc_redist.x64.exe >> release\使用说明.txt

echo       发布文件已准备完成
echo.

REM ============== 步骤6: 完成 ==============
echo [6/6] 打包完成!
echo.

REM 计算耗时
set END_TIME=%time%

echo ========================================
echo  打包成功!
echo ========================================
echo.
echo  输出文件: %EXE_FILE%
echo  文件大小: %EXE_SIZE_MB% MB
echo  发布目录: release\
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