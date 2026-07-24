# -*- coding: utf-8 -*-
"""
统一启动脚本
同时启动微信监控和股票分析服务（含终端看板）

使用方法:
    python start_all.py

启动后:
    - 微信监控在子进程运行
    - 股票分析服务在前台运行（含终端看板）
    - 按 Ctrl+C 同时停止两个服务
"""
import os
import sys
import subprocess
import signal
import time
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent


def start_wechat_monitor():
    """启动微信监控子进程"""
    monitor_script = PROJECT_ROOT / "src" / "main_exe.py"
    if not monitor_script.exists():
        print(f"[错误] 微信监控脚本不存在: {monitor_script}")
        return None

    print("[启动] 微信监控服务...")
    proc = subprocess.Popen(
        [sys.executable, str(monitor_script)],
        cwd=str(PROJECT_ROOT),
        creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0,
    )
    print(f"[OK] 微信监控已启动 (PID: {proc.pid}, 新窗口)")
    return proc


def start_stock_analysis():
    """启动股票分析服务（前台运行，含终端看板）"""
    print("[启动] 股票分析服务（含终端看板）...")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn",
             "src.stock_analysis.main:app",
             "--host", "0.0.0.0",
             "--port", "8000"],
            cwd=str(PROJECT_ROOT),
        )
        return proc
    except Exception as e:
        print(f"[错误] 股票分析服务启动失败: {e}")
        return None


def main():
    """主入口"""
    print("=" * 60)
    print("  微信群监控 + 股票分析 统一启动")
    print("=" * 60)
    print()

    processes = []

    # 1. 启动微信监控（新窗口）
    wechat_proc = start_wechat_monitor()
    if wechat_proc:
        processes.append(("微信监控", wechat_proc))

    # 2. 启动股票分析服务（当前窗口）
    stock_proc = start_stock_analysis()
    if stock_proc:
        processes.append(("股票分析", stock_proc))

    if not processes:
        print("[错误] 没有服务启动成功")
        return

    print()
    print("-" * 60)
    print("  所有服务已启动！")
    print("  - 微信监控: 新窗口运行")
    print("  - 股票分析: 当前窗口运行（含终端看板）")
    print("  - API服务: http://localhost:8000")
    print("  - 按 Ctrl+C 停止所有服务")
    print("-" * 60)

    # 等待进程结束
    try:
        while True:
            # 检查进程状态
            for name, proc in processes:
                retcode = proc.poll()
                if retcode is not None:
                    print(f"[警告] {name} 进程已退出 (返回码: {retcode})")

            time.sleep(5)
    except KeyboardInterrupt:
        print("\n[停止] 正在停止所有服务...")
        for name, proc in processes:
            try:
                proc.terminate()
                proc.wait(timeout=5)
                print(f"[OK] {name} 已停止")
            except subprocess.TimeoutExpired:
                proc.kill()
                print(f"[OK] {name} 已强制停止")
            except Exception as e:
                print(f"[警告] 停止{name}时出错: {e}")

        print("[完成] 所有服务已停止")


if __name__ == "__main__":
    main()