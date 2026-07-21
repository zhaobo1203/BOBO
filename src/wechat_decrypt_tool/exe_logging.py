"""EXE运行时日志模块

专为打包后的EXE设计的日志系统。
- 日志存放在EXE同级的 logs/ 目录
- 每次启动创建独立的日志文件（包含时间戳）
- 支持控制台彩色输出
- 支持环境变量控制日志级别
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class ColoredFormatter(logging.Formatter):
    """彩色日志格式化器"""

    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',      # 红色
        'CRITICAL': '\033[35m',   # 紫色
        'RESET': '\033[0m'
    }

    def format(self, record):
        formatted = super().format(record)
        
        # 只在控制台输出时添加颜色
        if hasattr(sys.stderr, 'isatty') and sys.stderr.isatty():
            level_color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
            reset_color = self.COLORS['RESET']
            formatted = formatted.replace(
                f'[{record.levelname}]',
                f'[{level_color}{record.levelname}{reset_color}]'
            )
        
        return formatted


def get_exe_dir() -> Path:
    """获取EXE所在目录（或脚本目录）"""
    if getattr(sys, 'frozen', False):
        # PyInstaller打包后的EXE
        return Path(sys.executable).parent
    else:
        # 开发环境，使用项目根目录
        return Path(__file__).resolve().parents[2]


def get_log_dir() -> Path:
    """获取日志目录（EXE同级logs目录）"""
    log_dir = get_exe_dir() / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_log_file() -> Path:
    """获取当前日志文件路径（包含时间戳，每次启动独立）"""
    # 使用进程ID和时间戳确保每次启动有独立的日志文件
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    pid = os.getpid()
    return get_log_dir() / f'monitor_{timestamp}_pid{pid}.log'


class ExeLoggerManager:
    """EXE日志管理器（单例）
    
    日志文件命名规则: monitor_YYYY-MM-DD_HHMMSS_pid<进程ID>.log
    每次程序启动都会创建新的日志文件，避免日志混乱。
    """
    
    _instance: Optional['ExeLoggerManager'] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def setup(self, log_level: str = 'INFO') -> Path:
        """设置日志系统
        
        Args:
            log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        
        Returns:
            日志文件路径
        """
        # 支持环境变量覆盖
        env_level = os.environ.get('WECHAT_LOG_LEVEL', '').strip().upper()
        if env_level in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'):
            log_level = env_level
        
        level = getattr(logging, log_level.upper(), logging.INFO)
        
        # 获取日志文件路径（每次启动创建新文件）
        log_file = get_log_file()
        
        # 如果已初始化，直接返回
        if self._initialized:
            return getattr(self, '_log_file', log_file)
        
        # 清除现有处理器
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
        
        # 日志格式
        file_format = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_format = ColoredFormatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        
        # 文件处理器
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(file_format)
        file_handler.setLevel(level)
        
        # 控制台处理器（仅在调试模式启用）
        console_handler = None
        if os.environ.get('WECHAT_DEBUG') == '1':
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(console_format)
            console_handler.setLevel(level)
        
        # 配置根日志器
        root_logger.setLevel(level)
        root_logger.addHandler(file_handler)
        if console_handler:
            root_logger.addHandler(console_handler)
        
        # 记录初始化信息
        logger = logging.getLogger(__name__)
        logger.info('=' * 50)
        logger.info('微信群消息监听系统启动')
        logger.info(f'日志文件: {log_file}')
        logger.info(f'日志级别: {log_level}')
        logger.info(f'进程ID: {os.getpid()}')
        if getattr(sys, 'frozen', False):
            logger.info(f'EXE路径: {sys.executable}')
        logger.info('=' * 50)
        
        # 保存状态
        self._log_file = log_file
        self._log_level = level
        self._initialized = True
        
        return log_file
    
    def get_log_file(self) -> Path:
        """获取当前日志文件路径"""
        if not self._initialized:
            self.setup()
        return self._log_file


def setup_exe_logging(log_level: str = 'INFO') -> Path:
    """设置EXE日志系统
    
    Args:
        log_level: 日志级别
    
    Returns:
        日志文件路径
    """
    manager = ExeLoggerManager()
    return manager.setup(log_level)


def get_exe_logger(name: str) -> logging.Logger:
    """获取日志器
    
    Args:
        name: 日志器名称（通常使用 __name__）
    
    Returns:
        Logger实例
    """
    if not ExeLoggerManager._initialized:
        setup_exe_logging()
    return logging.getLogger(name)


def get_log_file_path() -> Path:
    """获取当前日志文件路径"""
    manager = ExeLoggerManager()
    return manager.get_log_file()