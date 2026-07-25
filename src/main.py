#!/usr/bin/env python3
"""
微信群消息监听与股票分析系统 - 统一入口 v3.0.0
同时启动微信监控（模块1）和股票分析服务（模块3）
"""

import sys
import os
import threading
import multiprocessing
from pathlib import Path

# Windows PyInstaller 打包必须：防止 multiprocessing 子进程重新执行主程序
# 必须在程序最开始时调用，否则会导致程序卡死
multiprocessing.freeze_support()

# 添加项目路径
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).parent))


# 获取EXE所在目录（运行时数据根目录）
def get_app_dir() -> Path:
    """获取应用根目录

    打包后：EXE所在目录
    开发时：项目根目录（src的上级目录）
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).resolve().parents[1]


APP_DIR = get_app_dir()


def get_blacklist_path() -> Path:
    """获取blacklist.json路径

    打包后：从EXE内部临时解压目录读取
    开发时：从源码目录读取
    """
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / "stock_analysis" / "config" / "blacklist.json"
    else:
        return Path(__file__).parent / "stock_analysis" / "config" / "blacklist.json"


def redirect_settings_paths():
    """重定向模块3的配置路径到EXE同目录

    模块3的 settings.py 使用 Path(__file__).resolve().parents[3] 作为项目根目录，
    在打包后此路径指向临时解压目录，需要重定向到EXE同目录。
    """
    from stock_analysis.config import settings
    settings.PROJECT_ROOT = APP_DIR
    settings.A_STOCK_DB_PATH = APP_DIR / "data" / "a_stock_db" / "a_stock.db"
    settings.MESSAGES_DB_PATH = APP_DIR / "data" / "messages.db"
    settings.STOCK_MENTIONS_DB_PATH = APP_DIR / "data" / "stock_mentions.db"
    settings.LOG_DIR = APP_DIR / "logs"
    settings.BLACKLIST_PATH = get_blacklist_path()


def redirect_a_stock_db_paths():
    """重定向模块2的数据库路径到EXE同目录

    模块2的 database.py 使用 Path(__file__).parent.parent.parent / "data" / "a_stock_db"
    作为默认路径，在打包后此路径指向临时解压目录，需要重定向到EXE同目录。
    """
    from a_stock_db import database
    database.DEFAULT_DB_DIR = APP_DIR / "data" / "a_stock_db"
    database.DEFAULT_DB_PATH = database.DEFAULT_DB_DIR / "a_stock.db"


def redirect_message_storage_paths():
    """重定向模块1的消息存储路径到EXE同目录

    模块1的 message_storage.py 使用 Path(__file__).resolve().parents[2] / "data"
    作为默认路径，在打包后此路径指向临时解压目录，需要重定向到EXE同目录。
    """
    from wechat_decrypt_tool import message_storage
    message_storage.DEFAULT_DATA_DIR = APP_DIR / "data"
    message_storage.DEFAULT_DB_PATH = message_storage.DEFAULT_DATA_DIR / "messages.db"


def ensure_a_stock_db():
    """确保A股数据库存在于EXE同目录

    onefile模式下，打包在EXE内的文件运行时解压到临时目录（sys._MEIPASS）。
    首次运行时需要将A股数据库复制到EXE同目录。
    """
    target_path = APP_DIR / "data" / "a_stock_db" / "a_stock.db"
    if target_path.exists():
        return  # 已存在，无需释放

    if getattr(sys, 'frozen', False):
        source_path = Path(sys._MEIPASS) / "data" / "a_stock_db" / "a_stock.db"
        if source_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(str(source_path), str(target_path))
            print(f"  已释放A股数据库到: {target_path}")
        else:
            print(f"  [警告] EXE内部未找到A股数据库资源")
    else:
        # 开发模式：检查项目根目录的data
        source_path = APP_DIR / "data" / "a_stock_db" / "a_stock.db"
        if source_path.exists():
            print(f"  A股数据库已就绪: {source_path}")
        else:
            print(f"  [警告] 未找到A股数据库: {source_path}")


def ensure_directories():
    """确保运行时数据目录存在"""
    (APP_DIR / "data" / "a_stock_db").mkdir(parents=True, exist_ok=True)
    (APP_DIR / "data").mkdir(parents=True, exist_ok=True)
    (APP_DIR / "logs").mkdir(parents=True, exist_ok=True)
    (APP_DIR / "output").mkdir(parents=True, exist_ok=True)


def start_fastapi_server():
    """在后台线程启动FastAPI服务

    FastAPI服务在后台线程中启动，不阻塞主线程的微信监控交互。
    uvicorn日志重定向到文件，避免HTTP请求日志干扰控制台显示。
    """
    import uvicorn
    import logging

    # 重定向路径配置
    redirect_settings_paths()
    redirect_a_stock_db_paths()
    redirect_message_storage_paths()

    # 确保目录存在
    ensure_directories()

    # 释放A股数据库
    ensure_a_stock_db()

    # 配置uvicorn日志：access log和error log只写文件，不输出到控制台
    # 这样避免HTTP请求日志干扰看板和微信监控的终端显示
    log_config = uvicorn.config.LOGGING_CONFIG.copy()

    # 移除默认的console handler，改为file handler
    uvicorn_log_file = str(APP_DIR / "logs" / "uvicorn.log")
    log_config["handlers"] = {
        "default": {
            "class": "logging.FileHandler",
            "filename": uvicorn_log_file,
            "formatter": "default",
            "encoding": "utf-8",
        },
        "access": {
            "class": "logging.FileHandler",
            "filename": uvicorn_log_file,
            "formatter": "access",
            "encoding": "utf-8",
        },
    }
    # 将uvicorn的logger指向file handler
    log_config["loggers"]["uvicorn"]["handlers"] = ["default"]
    log_config["loggers"]["uvicorn.error"]["handlers"] = ["default"]
    log_config["loggers"]["uvicorn.access"]["handlers"] = ["access"]

    def run_server():
        uvicorn.run(
            "stock_analysis.main:app",
            host="0.0.0.0",
            port=8000,
            log_level="info",
            log_config=log_config,
        )

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    return server_thread


def main():
    """主函数 - 统一入口"""
    print()
    print("=" * 60)
    print("    微信群消息监听与股票分析系统 v3.0.0")
    print("=" * 60)
    print()

    # 显示应用根目录
    print(f"  应用目录: {APP_DIR}")
    print()

    # 1. 启动FastAPI服务（后台线程）
    print("  [..] 启动股票分析服务...")
    try:
        server_thread = start_fastapi_server()
        print("  [OK] 股票分析服务已启动 (http://localhost:8000)")
    except Exception as e:
        print(f"  [FAIL] 股票分析服务启动失败: {e}")
        print(f"  继续启动微信监控...")
    print()

    # 2. 启动终端看板（后台线程，追加模式）
    print("  [..] 启动终端看板...")
    try:
        from stock_analysis.dashboard import start_dashboard_thread
        dashboard_controller = start_dashboard_thread()
        print("  [OK] 终端看板已启动（追加模式，120秒自动刷新）")
    except Exception as e:
        print(f"  [FAIL] 终端看板启动失败: {e}")
        dashboard_controller = None
    print()

    # 3. 运行微信监控（主线程）
    print("  [..] 启动微信监控...")
    print()

    try:
        from simple_monitor import SimpleMonitor
        monitor = SimpleMonitor()
        monitor.run()
    except KeyboardInterrupt:
        print('\n\n[用户中断]')
        sys.exit(0)
    except Exception as e:
        # 记录异常到日志
        import logging
        logger = logging.getLogger(__name__)
        logger.exception(f"程序发生未捕获异常: {e}")

        # 显示友好的错误信息
        print()
        print("=" * 60)
        print("  程序遇到错误，抱歉!")
        print("=" * 60)
        print()
        print(f"  错误类型: {type(e).__name__}")
        print(f"  错误信息: {str(e)[:100]}")
        print()
        print("  可能的解决方案:")
        print("  1. 确保微信已登录")
        print("  2. 以管理员权限运行程序")
        print("  3. 检查杀毒软件是否拦截")
        print()
        input("  按 Enter 键退出...")
        sys.exit(1)


if __name__ == '__main__':
    main()