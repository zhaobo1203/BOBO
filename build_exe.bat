@echo off
chcp 65001 >nul
echo ========================================
echo  微信群消息监听系统 - 打包脚本
echo ========================================
echo.

REM 检查Python环境
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python环境，请先安装Python 3.11+
    pause
    exit /b 1
)

REM 检查PyInstaller
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [信息] 正在安装PyInstaller...
    pip install pyinstaller -q
)

REM 清理旧的打包文件
if exist "dist\微信群消息监听.exe" (
    echo [信息] 清理旧的EXE文件...
    del /f "dist\微信群消息监听.exe"
)

REM 执行打包
echo [信息] 开始打包...
echo.

pyinstaller --clean --noconfirm "微信群消息监听.spec"

if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请检查错误信息
    pause
    exit /b 1
)

echo.
echo ========================================
echo  打包完成！
echo ========================================
echo.
echo  输出文件: dist\微信群消息监听.exe
echo.

REM 检查输出文件
if exist "dist\微信群消息监听.exe" (
    echo  文件大小:
    for %%I in ("dist\微信群消息监听.exe") do echo    %%~zI 字节
    echo.
    echo  使用方法: 将 dist\微信群消息监听.exe 复制到任意目录运行
)

echo.
pause