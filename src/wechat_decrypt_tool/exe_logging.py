"""
EXE日志模块 - 向后兼容代理

此模块现在是对 logging_config 的简单代理，保持向后兼容。
所有日志功能已统一到 logging_config.py 中的 UnifiedLogManager。

功能：
- 双格式输出：纯文本(.log) + JSON(.json)
- 按日期分割：每天一个文件
- 自动清理：保留最近30天
- 分级输出：文件DEBUG+，控制台INFO+
- 完整堆栈：异常时记录完整traceback

日志文件结构：
logs/
├── app_2026-07-22.log      # 纯文本日志
├── app_2026-07-22.json     # JSON日志
└── ...                     # 最多保留30天
"""

from pathlib import Path

# 从统一日志模块导入所有功能
from .logging_config import (
    setup_logging,
    get_logger,
    get_log_file_path,
    get_tn_logger,
    TNLoggerAdapter,
    LOG_RETENTION_DAYS,
)


# ============================================================================
# 向后兼容的便捷函数
# ============================================================================

def setup_exe_logging(log_level: str = 'INFO') -> Path:
    """设置统一日志系统（向后兼容）

    Args:
        log_level: 日志级别（保留参数，实际使用分级策略）

    Returns:
        日志文件路径
    """
    return setup_logging(log_level)


def get_exe_logger(name: str) -> 'logging.Logger':
    """获取日志器（向后兼容）

    Args:
        name: 日志器名称（通常使用 __name__）

    Returns:
        Logger实例
    """
    return get_logger(name)


def get_exe_dir() -> Path:
    """获取EXE所在目录（兼容开发环境和打包环境）
    
    Returns:
        EXE目录或项目根目录
    """
    import sys
    if getattr(sys, 'frozen', False):
        # 打包后的EXE
        return Path(sys.executable).parent
    else:
        # 开发环境，使用项目根目录
        return Path(__file__).resolve().parents[2]


# ============================================================================
# 导出公共API
# ============================================================================

__all__ = [
    'setup_exe_logging',
    'get_exe_logger',
    'get_exe_dir',
    'get_log_file_path',
    'get_tn_logger',
    'TNLoggerAdapter',
    'LOG_RETENTION_DAYS',
]