#!/usr/bin/env python3
"""
微信群消息监听与股票分析系统 - 统一入口 v3.0.0
同时启动微信监控（模块1）和股票分析服务（模块3）
"""

import sys
import os
import logging
import threading
import multiprocessing
from pathlib import Path

# Windows PyInstaller 打包必须：防止 multiprocessing 子进程重新执行主程序
# 必须在程序最开始时调用，否则会导致程序卡死
multiprocessing.freeze_support()

# 添加项目路径
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).parent))

from common_utils import display_error_and_exit


def get_app_dir() -> Path:
    """获取应用根目录

    打包后：EXE所在目录
    开发时：项目根目录（src的上级目录）
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[1]


APP_DIR = get_app_dir()


def get_blacklist_path() -> Path:
    """获取blacklist.json路径

    打包后：从EXE内部临时解压目录读取
    开发时：从源码目录读取
    """
    base = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).parent
    return base / "stock_analysis" / "config" / "blacklist.json"


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


def _verify_a_stock_db(db_path: Path) -> bool:
    """验证A股数据库表结构完整性

    检查数据库是否包含必要的表（stocks, update_log），
    防止空数据库或损坏的数据库被当作有效数据库使用。

    Args:
        db_path: 数据库文件路径

    Returns:
        True 如果数据库表结构完整，False 否则
    """
    import sqlite3

    if not db_path.exists():
        print(f"  [警告] A股数据库文件不存在: {db_path}")
        return False

    try:
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

            required_tables = {'stocks', 'update_log'}
            if not required_tables.issubset(tables):
                print(f"  [警告] A股数据库缺少表: {required_tables - tables}")
                return False

            # 验证stocks表是否有数据
            cursor.execute("SELECT COUNT(*) FROM stocks")
            if cursor.fetchone()[0] == 0:
                print(f"  [警告] A股数据库stocks表为空（0条记录）")
                return False

            return True
    except Exception as e:
        print(f"  [警告] A股数据库验证失败: {e}")
        return False


def _get_a_stock_db_source_path() -> Path:
    """获取A股数据库的源路径（打包时从MEIPASS读取，开发时从项目目录读取）"""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / "data" / "a_stock_db" / "a_stock.db"
    return APP_DIR / "data" / "a_stock_db" / "a_stock.db"


def ensure_a_stock_db():
    """确保A股数据库存在于EXE同目录且表结构完整

    onefile模式下，打包在EXE内的文件运行时解压到临时目录（sys._MEIPASS）。
    首次运行时需要将A股数据库复制到EXE同目录。
    如果已存在的数据库表结构不完整（如空数据库），会重新释放。
    """
    target_path = APP_DIR / "data" / "a_stock_db" / "a_stock.db"

    # 检查目标数据库是否存在且表结构完整
    if target_path.exists():
        if _verify_a_stock_db(target_path):
            return  # 数据库完整，无需操作
        # 数据库存在但表结构不完整，需要重新释放
        print(f"  [修复] A股数据库表结构不完整，尝试重新释放...")
        try:
            target_path.unlink()
        except OSError as e:
            print(f"  [警告] 无法删除损坏的数据库: {e}")
            return  # 无法删除，放弃操作

    source_path = _get_a_stock_db_source_path()

    if getattr(sys, 'frozen', False):
        if source_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            try:
                shutil.copy2(str(source_path), str(target_path))
                # 验证释放后的数据库
                if _verify_a_stock_db(target_path):
                    print(f"  已释放A股数据库到: {target_path}")
                else:
                    print(f"  [警告] 释放的A股数据库仍不完整，将通过API初始化")
            except OSError as e:
                print(f"  [警告] 复制A股数据库失败: {e}")
        else:
            print(f"  [警告] EXE内部未找到A股数据库资源，将通过API初始化")
    else:
        # 开发模式：检查项目根目录的data
        if source_path.exists():
            if _verify_a_stock_db(source_path):
                print(f"  A股数据库已就绪: {source_path}")
            else:
                print(f"  [警告] A股数据库表结构不完整: {source_path}")
        else:
            print(f"  [警告] 未找到A股数据库: {source_path}")


def ensure_directories():
    """确保运行时数据目录存在"""
    required_dirs = [
        APP_DIR / "data" / "a_stock_db",
        APP_DIR / "data",
        APP_DIR / "logs",
        APP_DIR / "output",
    ]
    for dir_path in required_dirs:
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"  [警告] 创建目录失败 {dir_path}: {e}")


def _is_port_in_use(port: int) -> bool:
    """检查端口是否被占用"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return False
        except OSError:
            return True


def _find_available_port(start_port: int = 8000, max_tries: int = 100) -> int:
    """从start_port开始寻找可用端口"""
    for port in range(start_port, start_port + max_tries):
        if not _is_port_in_use(port):
            return port
    return start_port  # 找不到则返回原始端口


def start_fastapi_server():
    """在后台线程启动FastAPI服务

    FastAPI服务在后台线程中启动，不阻塞主线程的微信监控交互。
    uvicorn日志重定向到文件，避免HTTP请求日志干扰控制台显示。
    支持端口冲突自动切换：当默认端口被占用时，自动寻找可用端口。
    """
    import uvicorn

    # 重定向路径配置
    redirect_settings_paths()
    redirect_a_stock_db_paths()
    redirect_message_storage_paths()

    # 确保目录存在
    ensure_directories()

    # 释放A股数据库
    ensure_a_stock_db()

    # 检测端口可用性，自动切换
    default_port = 8000
    actual_port = default_port
    if _is_port_in_use(default_port):
        actual_port = _find_available_port(default_port + 1)
        if actual_port != default_port:
            print(f"  [!] 端口 {default_port} 已被占用，自动切换到端口 {actual_port}")

    # 更新模块3的API端口配置，确保内部调用一致
    from stock_analysis.config import settings
    settings.API_PORT = actual_port

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
            port=actual_port,
            log_level="info",
            log_config=log_config,
        )

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    return server_thread, actual_port


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
    api_port = 8000  # 默认端口
    try:
        server_thread, api_port = start_fastapi_server()
        print(f"  [OK] 股票分析服务已启动 (http://localhost:{api_port})")
    except Exception as e:
        print(f"  [FAIL] 股票分析服务启动失败: {e}")
        print(f"  继续启动微信监控...")
    print()

    # 2. 启动终端看板（后台线程，追加模式）
    print("  [..] 启动终端看板...")
    dashboard_controller = None
    try:
        from stock_analysis.dashboard import start_dashboard_thread, set_api_base
        # 动态设置看板API地址，与实际启动端口一致
        set_api_base(f"http://localhost:{api_port}")
        dashboard_controller = start_dashboard_thread()
        print("  [OK] 终端看板已启动（追加模式，120秒自动刷新）")
    except Exception as e:
        print(f"  [FAIL] 终端看板启动失败: {e}")
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
        logger = logging.getLogger(__name__)
        logger.exception(f"程序发生未捕获异常: {e}")

        # 使用公共模块显示错误
        display_error_and_exit(e)


if __name__ == '__main__':
    main()