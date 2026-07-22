"""统一日志模块

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

import json
import logging
import os
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# 日志保留天数
LOG_RETENTION_DAYS = 30


class JsonFormatter(logging.Formatter):
    """JSON格式日志格式化器"""

    def format(self, record):
        log_data = {
            'time': self.formatTime(record, self.datefmt),
            'level': record.levelname,
            'module': record.name,
            'message': record.getMessage()
        }

        # 添加额外字段
        if hasattr(record, 'tn_module'):
            log_data['tn_module'] = record.tn_module

        # 异常信息
        if record.exc_info:
            log_data['traceback'] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


class ColoredFormatter(logging.Formatter):
    """彩色日志格式化器（控制台）"""

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

        # 只在支持ANSI的终端添加颜色
        if hasattr(sys.stderr, 'isatty') and sys.stderr.isatty():
            level_color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
            reset_color = self.COLORS['RESET']
            formatted = formatted.replace(
                f'[{record.levelname}]',
                f'[{level_color}{record.levelname}{reset_color}]'
            )

        return formatted


class TNLoggerAdapter(logging.LoggerAdapter):
    """TN模块日志适配器，支持添加模块标签"""

    def process(self, msg, kwargs):
        # 添加TN模块标签
        if 'extra' not in kwargs:
            kwargs['extra'] = {}
        kwargs['extra']['tn_module'] = self.extra.get('tn_module', 'APP')
        return f"[{self.extra.get('tn_module', 'APP')}] {msg}", kwargs


class LogManager:
    """日志管理器（单例）

    统一管理所有日志，输出到：
    - 文件：app_YYYY-MM-DD.log（纯文本）
    - 文件：app_YYYY-MM-DD.json（JSON格式）
    - 控制台：INFO及以上
    """

    _instance: Optional['LogManager'] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def setup(self) -> Path:
        """设置日志系统

        Returns:
            日志文件路径（不含扩展名）
        """
        if self._initialized:
            return self._log_base

        # 日志目录
        log_dir = self._get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)

        # 清理旧日志
        self._cleanup_old_logs(log_dir)

        # 当前日志文件（按日期）
        today = datetime.now().strftime('%Y-%m-%d')
        self._log_base = log_dir / f'app_{today}'

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
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_format = ColoredFormatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%H:%M:%S'
        )

        # 纯文本文件处理器（DEBUG及以上）
        log_file = self._log_base.with_suffix('.log')
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(file_format)
        file_handler.setLevel(logging.DEBUG)

        # JSON文件处理器（DEBUG及以上）
        json_file = self._log_base.with_suffix('.json')
        json_handler = logging.FileHandler(json_file, encoding='utf-8')
        json_handler.setFormatter(JsonFormatter(
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        json_handler.setLevel(logging.DEBUG)

        # 控制台处理器（INFO及以上）
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(console_format)
        console_handler.setLevel(logging.INFO)

        # 配置根日志器
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(file_handler)
        root_logger.addHandler(json_handler)
        root_logger.addHandler(console_handler)

        # 记录启动信息
        logger = logging.getLogger(__name__)
        logger.info('=' * 60)
        logger.info('微信群消息监听系统 v1.0 启动')
        logger.info(f'日志文件: {log_file}')
        logger.info(f'JSON日志: {json_file}')
        logger.info(f'进程ID: {os.getpid()}')
        logger.info('=' * 60)

        self._initialized = True
        return self._log_base

    def _get_log_dir(self) -> Path:
        """获取日志目录"""
        if getattr(sys, 'frozen', False):
            # 打包后的EXE
            return Path(sys.executable).parent / 'logs'
        else:
            # 开发环境，使用项目根目录
            return Path(__file__).resolve().parents[2] / 'logs'

    def _cleanup_old_logs(self, log_dir: Path):
        """清理超过保留天数的日志文件"""
        cutoff_date = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)

        for log_file in log_dir.glob('app_*.log*'):
            try:
                # 从文件名提取日期 (app_YYYY-MM-DD.log)
                filename = log_file.stem  # app_2026-07-22
                date_str = filename.replace('app_', '')
                file_date = datetime.strptime(date_str, '%Y-%m-%d')

                if file_date < cutoff_date:
                    log_file.unlink(missing_ok=True)
                    logging.getLogger(__name__).debug(
                        f'清理过期日志: {log_file.name}'
                    )
            except (ValueError, OSError):
                # 文件名格式不匹配或删除失败，跳过
                pass

    def get_log_file(self) -> Path:
        """获取当前日志文件路径"""
        if not self._initialized:
            self.setup()
        return self._log_base.with_suffix('.log')


def setup_exe_logging(log_level: str = 'INFO') -> Path:
    """设置统一日志系统

    Args:
        log_level: 日志级别（保留参数，实际使用分级策略）

    Returns:
        日志文件路径
    """
    manager = LogManager()
    return manager.setup()


def get_exe_logger(name: str) -> logging.Logger:
    """获取日志器

    Args:
        name: 日志器名称（通常使用 __name__）

    Returns:
        Logger实例
    """
    if not LogManager._initialized:
        setup_exe_logging()
    return logging.getLogger(name)


def get_tn_logger(tn_module: str) -> TNLoggerAdapter:
    """获取TN模块专用日志器

    Args:
        tn_module: TN模块名称（如 TN-01, TN-02）

    Returns:
        带TN标签的Logger适配器
    """
    if not LogManager._initialized:
        setup_exe_logging()
    logger = logging.getLogger(f'wechat.{tn_module}')
    return TNLoggerAdapter(logger, {'tn_module': tn_module})


def get_exe_dir() -> Path:
    """获取EXE所在目录（兼容开发环境和打包环境）
    
    Returns:
        EXE目录或项目根目录
    """
    if getattr(sys, 'frozen', False):
        # 打包后的EXE
        return Path(sys.executable).parent
    else:
        # 开发环境，使用项目根目录
        return Path(__file__).resolve().parents[2]


def get_log_file_path() -> Path:
    """获取当前日志文件路径"""
    manager = LogManager()
    return manager.get_log_file()


# 便捷函数
def get_app_logger() -> logging.Logger:
    """获取应用主日志器"""
    return get_exe_logger('wechat')