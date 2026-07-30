#!/usr/bin/env python3
"""
公共工具模块 - 提供两个主模块共用的工具函数

包含：
- 异常显示函数
- 时间戳解析辅助函数
- 目录遍历查找辅助函数
- 消息处理辅助函数
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Any


def display_error_and_exit(error: Exception, exit_code: int = 1) -> None:
    """显示友好的错误信息并退出程序
    
    统一的错误显示格式，用于 main.py 和 simple_monitor.py
    
    Args:
        error: 捕获的异常对象
        exit_code: 退出码，默认为 1
    """
    print()
    print("=" * 60)
    print("  程序遇到错误，抱歉!")
    print("=" * 60)
    print()
    print(f"  错误类型: {type(error).__name__}")
    print(f"  错误信息: {str(error)[:100]}")
    print()
    print("  可能的解决方案:")
    print("  1. 确保微信已登录")
    print("  2. 以管理员权限运行程序")
    print("  3. 检查杀毒软件是否拦截")
    print()
    input("  按 Enter 键退出...")
    sys.exit(exit_code)


def parse_timestamp(timestamp: Any) -> int:
    """安全解析时间戳为整数
    
    处理各种可能的时间戳格式，返回整数时间戳或 0
    
    Args:
        timestamp: 时间戳值（可能是 int, float, str, None 等）
        
    Returns:
        整数时间戳，解析失败返回 0
    """
    if timestamp is None:
        return 0
    try:
        return int(timestamp) if timestamp else 0
    except (ValueError, TypeError):
        return 0


def format_timestamp(timestamp: int, fmt: str = '%H:%M:%S') -> str:
    """格式化时间戳为字符串
    
    Args:
        timestamp: 整数时间戳
        fmt: 格式化字符串，默认为 '%H:%M:%S'
        
    Returns:
        格式化后的时间字符串，无效时间戳返回 '--:--:--'
    """
    if not timestamp:
        return '--:--:--' if fmt == '%H:%M:%S' else '无'
    try:
        return datetime.fromtimestamp(timestamp).strftime(fmt)
    except (ValueError, OSError):
        return '--:--:--' if fmt == '%H:%M:%S' else '无'


def truncate_text(text: str, max_len: int = 30, suffix: str = '...') -> str:
    """截断过长的文本
    
    Args:
        text: 原始文本
        max_len: 最大长度
        suffix: 截断后添加的后缀
        
    Returns:
        截断后的文本
    """
    if not text:
        return ''
    if len(text) <= max_len:
        return text
    return text[:max_len - len(suffix)] + suffix


def find_session_db_in_dir(base_path: Path, skip_dirs: Optional[set] = None) -> Optional[Path]:
    """在指定目录下查找 session.db 文件
    
    查找优先级：
    1. db_storage/session/session.db
    2. db_storage/session.db
    
    Args:
        base_path: 基础目录路径
        skip_dirs: 要跳过的目录名集合（小写）
        
    Returns:
        找到的 session.db 路径，未找到返回 None
    """
    if skip_dirs is None:
        skip_dirs = {'all users', 'applet', 'wmpf', 'backup', 'config', 'cache'}
    
    if not base_path.exists() or not base_path.is_dir():
        return None
    
    # 直接检查常见路径
    direct_paths = [
        base_path / 'db_storage' / 'session' / 'session.db',
        base_path / 'db_storage' / 'session.db',
        base_path / 'session.db',
    ]
    
    for path in direct_paths:
        if path.exists():
            return path
    
    return None


def find_account_dir_with_session(base_path: Path, account_id: Optional[str] = None,
                                   skip_dirs: Optional[set] = None) -> Optional[Path]:
    """查找包含有效 session.db 的账号目录
    
    遍历目录结构，找到包含有效 db_storage 的账号子目录
    
    Args:
        base_path: 基础目录路径
        account_id: 可选的账号ID，用于匹配目录名
        skip_dirs: 要跳过的目录名集合（小写）
        
    Returns:
        找到的账号目录路径，未找到返回 None
    """
    if skip_dirs is None:
        skip_dirs = {'all users', 'applet', 'wmpf', 'backup', 'config', 'cache'}
    
    if not base_path.exists() or not base_path.is_dir():
        return None
    
    try:
        for sub_dir in base_path.iterdir():
            if not sub_dir.is_dir():
                continue
            
            dir_name_lower = sub_dir.name.lower()
            if dir_name_lower in skip_dirs:
                continue
            
            # 如果指定了账号ID，检查目录名是否匹配
            if account_id and account_id.lower() not in dir_name_lower:
                continue
            
            # 检查是否包含有效的 session.db
            session_db = find_session_db_in_dir(sub_dir, skip_dirs)
            if session_db:
                return sub_dir
                
    except (PermissionError, OSError):
        pass
    
    return None


def get_log_file_path(log_dir: Optional[Path] = None) -> Optional[Path]:
    """获取最新的日志文件路径
    
    Args:
        log_dir: 日志目录，如果为 None 则尝试自动查找
        
    Returns:
        最新的日志文件路径，未找到返回 None
    """
    if log_dir is None:
        # 尝试从当前工作目录查找
        log_dir = Path.cwd() / 'logs'
    
    if not log_dir.exists():
        return None
    
    # 查找最新的日志文件
    log_files = list(log_dir.glob('app_*.log'))
    if not log_files:
        log_files = list(log_dir.glob('*.log'))
    
    if log_files:
        return max(log_files, key=lambda f: f.stat().st_mtime)
    
    return None