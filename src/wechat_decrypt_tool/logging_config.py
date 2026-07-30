"""
统一的日志配置模块

根据《变更提案：日志系统全面重构方案.md》实现：
- 环境感知配置（Environment, LogConfig）
- 双通道日志（用户日志 + 系统日志）
- 错误收敛机制
- request_id链路追踪
- 统一日志出口

所有模块应通过此模块获取日志器，避免直接使用 logging.getLogger()
"""

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ============================================================================
# 常量定义
# ============================================================================

# ANSI颜色代码 - 统一定义，全局唯一
LOG_COLORS = {
    'DEBUG': '\033[36m',      # 青色
    'INFO': '\033[32m',       # 绿色
    'WARNING': '\033[33m',    # 黄色
    'ERROR': '\033[31m',      # 红色
    'CRITICAL': '\033[35m',   # 紫色
    'RESET': '\033[0m'        # 重置
}

# 日志保留天数
LOG_RETENTION_DAYS = 30


# ============================================================================
# 环境感知配置
# ============================================================================

class Environment(Enum):
    """运行环境枚举"""
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


@dataclass
class LogConfig:
    """日志配置 - 根据变更提案定义"""
    level: str = "INFO"
    format_type: str = "text"  # text 或 json
    outputs: List[str] = field(default_factory=lambda: ["file"])
    include_caller: bool = False
    include_stack_trace: bool = False
    include_request_id: bool = True
    include_user_id: bool = False
    include_execution_time: bool = False
    
    @classmethod
    def get_config(cls, env: Environment = Environment.DEVELOPMENT) -> 'LogConfig':
        """根据环境获取配置（统一工厂方法）"""
        configs = {
            Environment.DEVELOPMENT: cls(
                level="DEBUG",
                format_type="text",
                outputs=["console", "file"],
                include_caller=True,
                include_stack_trace=True,
                include_request_id=True,
                include_user_id=True,
                include_execution_time=True
            ),
            Environment.TESTING: cls(
                level="DEBUG",
                format_type="text",
                outputs=["file"],
                include_caller=True,
                include_stack_trace=True,
                include_request_id=True,
                include_user_id=False,
                include_execution_time=True
            ),
            Environment.PRODUCTION: cls(
                level="INFO",
                format_type="json",
                outputs=["file"],
                include_caller=False,
                include_stack_trace=False,
                include_request_id=True,
                include_user_id=False,
                include_execution_time=False
            ),
        }
        return configs.get(env, configs[Environment.DEVELOPMENT])
    
    # 保持向后兼容的类方法
    @classmethod
    def dev_config(cls) -> 'LogConfig':
        """开发环境配置 - 全量输出"""
        return cls.get_config(Environment.DEVELOPMENT)
    
    @classmethod
    def prod_config(cls) -> 'LogConfig':
        """生产环境配置 - 精简输出"""
        return cls.get_config(Environment.PRODUCTION)
    
    @classmethod
    def test_config(cls) -> 'LogConfig':
        """测试环境配置"""
        return cls.get_config(Environment.TESTING)


# ============================================================================
# 格式化器（统一实现）
# ============================================================================

class BaseFormatter(logging.Formatter):
    """格式化器基类"""
    
    def formatTime(self, record, datefmt=None):
        """格式化时间，确保毫秒精度"""
        import time
        ct = self.converter(record.created)
        if datefmt:
            return time.strftime(datefmt, ct)
        return time.strftime('%Y-%m-%d %H:%M:%S', ct)


class TextFormatter(BaseFormatter):
    """文本格式化器 - 开发环境使用"""
    
    def __init__(self, include_caller: bool = False):
        self.include_caller = include_caller
        fmt = '%(asctime)s | %(levelname)s | %(message)s'
        if include_caller:
            fmt = '%(asctime)s | %(levelname)s | %(name)s | %(message)s'
        super().__init__(fmt, datefmt='%Y-%m-%d %H:%M:%S')
    
    def format(self, record):
        # 添加调用位置信息
        if self.include_caller and hasattr(record, 'pathname'):
            record.name = f"{record.name} ({record.pathname}:{record.lineno})"
        return super().format(record)


class JsonFormatter(BaseFormatter):
    """JSON格式化器 - 生产环境使用"""
    
    def __init__(self, include_caller: bool = False, include_stack_trace: bool = False):
        self.include_caller = include_caller
        self.include_stack_trace = include_stack_trace
        super().__init__()
    
    def format(self, record):
        log_data = {
            'timestamp': self.formatTime(record),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage()
        }
        
        if self.include_caller and hasattr(record, 'pathname'):
            log_data['caller'] = f"{record.pathname}:{record.lineno}"
            log_data['function'] = record.funcName
        
        if record.exc_info and self.include_stack_trace:
            log_data['stack_trace'] = self.formatException(record.exc_info)
        
        if hasattr(record, 'context') and record.context:
            log_data['context'] = record.context
        
        # TN模块标签（兼容exe_logging）
        if hasattr(record, 'tn_module'):
            log_data['tn_module'] = record.tn_module
        
        # 安全序列化，处理不可序列化的对象
        try:
            return json.dumps(log_data, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return json.dumps({
                'timestamp': self.formatTime(record),
                'level': record.levelname,
                'message': record.getMessage(),
                'error': 'Failed to serialize log data'
            }, ensure_ascii=False)


class ColoredFormatter(BaseFormatter):
    """彩色日志格式化器 - 使用统一的LOG_COLORS"""

    def __init__(self, fmt: str = None, datefmt: str = None):
        fmt = fmt or '%(asctime)s | %(levelname)s | %(name)s | %(message)s'
        datefmt = datefmt or '%Y-%m-%d %H:%M:%S'
        super().__init__(fmt, datefmt=datefmt)

    def format(self, record):
        formatted = super().format(record)

        # 只在控制台输出时添加颜色
        if hasattr(sys.stderr, 'isatty') and sys.stderr.isatty():
            level_color = LOG_COLORS.get(record.levelname, LOG_COLORS['RESET'])
            reset_color = LOG_COLORS['RESET']

            # 为日志级别添加颜色
            formatted = formatted.replace(
                f' | {record.levelname} | ',
                f' | {level_color}{record.levelname}{reset_color} | '
            )

        return formatted


class ConsoleFormatter(BaseFormatter):
    """控制台彩色格式化器 - 使用统一的LOG_COLORS"""
    
    def __init__(self):
        super().__init__('%(asctime)s [%(levelname)s] %(message)s', 
                         datefmt='%H:%M:%S')
    
    def format(self, record):
        formatted = super().format(record)
        if sys.stdout.isatty():
            color = LOG_COLORS.get(record.levelname, LOG_COLORS['RESET'])
            reset = LOG_COLORS['RESET']
            formatted = f"{color}{formatted}{reset}"
        return formatted


# ============================================================================
# TN模块日志适配器（兼容exe_logging）
# ============================================================================

class TNLoggerAdapter(logging.LoggerAdapter):
    """TN模块日志适配器，支持添加模块标签"""

    def process(self, msg, kwargs):
        # 添加TN模块标签
        if 'extra' not in kwargs:
            kwargs['extra'] = {}
        kwargs['extra']['tn_module'] = self.extra.get('tn_module', 'APP')
        return f"[{self.extra.get('tn_module', 'APP')}] {msg}", kwargs


# ============================================================================
# 双通道日志器
# ============================================================================

class DualChannelLogger:
    """双通道日志器 - 用户日志 + 系统日志分离
    
    根据变更提案，日志系统应支持：
    1. 用户日志通道 - 用户友好的中文提示
    2. 系统日志通道 - 技术细节
    3. 错误收敛 - 同类错误只提示一次
    """
    
    def __init__(self, name: str, config: LogConfig, log_dir: Path):
        self.name = name
        self.config = config
        self.log_dir = Path(log_dir)  # 确保是Path类型
        
        # 创建日志目录，处理可能的异常
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            # 降级到临时目录
            import tempfile
            self.log_dir = Path(tempfile.gettempdir()) / "wechat_logs" / name
            self.log_dir.mkdir(parents=True, exist_ok=True)
            logging.warning(f"无法创建日志目录 {log_dir}，已降级到 {self.log_dir}: {e}")
        
        # 用户日志器（用户可见）
        self.user_logger = self._create_logger(
            f"{name}.user", 
            "user.log",
            user_friendly=True
        )
        
        # 系统日志器（技术细节）
        self.system_logger = self._create_logger(
            f"{name}.system",
            "system.log",
            user_friendly=False
        )
        
        # 错误收敛集合
        self._shown_errors: Set[str] = set()
    
    def _create_logger(self, logger_name: str, filename: str, 
                       user_friendly: bool = False) -> logging.Logger:
        """创建日志器"""
        logger = logging.getLogger(logger_name)
        logger.setLevel(getattr(logging, self.config.level))
        logger.handlers = []  # 清除现有处理器
        
        # 文件处理器
        file_path = self.log_dir / filename
        try:
            file_handler = logging.FileHandler(file_path, encoding='utf-8')
        except (OSError, PermissionError) as e:
            # 降级到临时目录
            import tempfile
            fallback_path = Path(tempfile.gettempdir()) / "wechat_logs" / filename
            fallback_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(fallback_path, encoding='utf-8')
            logging.warning(f"无法创建日志文件 {file_path}，已降级到 {fallback_path}: {e}")
        
        # 根据配置选择格式化器
        if self.config.format_type == "json":
            formatter = JsonFormatter(
                include_caller=self.config.include_caller,
                include_stack_trace=self.config.include_stack_trace
            )
        else:
            formatter = TextFormatter(
                include_caller=self.config.include_caller
            )
        
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        # 控制台处理器（仅开发环境且用户日志）
        if "console" in self.config.outputs and user_friendly:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(ConsoleFormatter())
            logger.addHandler(console_handler)
        
        return logger
    
    # ========== 用户日志接口 ==========
    
    def user_info(self, message: str):
        """用户信息提示"""
        self.user_logger.info(message)
    
    def user_warn(self, message: str):
        """用户警告提示"""
        self.user_logger.warning(message)
    
    def user_error(self, message: str, error_type: Optional[str] = None):
        """用户错误提示（带收敛）"""
        if error_type:
            if error_type in self._shown_errors:
                return  # 已显示过，不重复
            self._shown_errors.add(error_type)
        self.user_logger.error(message)
    
    def clear_shown_errors(self):
        """清除已显示错误集合（用于测试或重置）"""
        self._shown_errors.clear()
    
    # ========== 系统日志接口 ==========
    
    def debug(self, message: str, **context):
        """调试日志 - 开发专用：变量值、循环迭代、SQL语句、API请求/响应体"""
        extra = {"context": context} if context else {}
        self.system_logger.debug(message, extra=extra)
    
    def info(self, message: str, **context):
        """信息日志 - 运行里程碑：服务启动/停止、配置加载完成、核心流程节点"""
        extra = {"context": context} if context else {}
        self.system_logger.info(message, extra=extra)
    
    def warn(self, message: str, **context):
        """警告日志 - 可恢复异常：请求重试、降级处理、非关键依赖超时"""
        extra = {"context": context} if context else {}
        self.system_logger.warning(message, extra=extra)
    
    def error(self, message: str, exc_info: bool = False, **context):
        """错误日志 - 功能受损：业务逻辑失败、数据异常、必要资源不可用"""
        extra = {"context": context} if context else {}
        self.system_logger.error(message, exc_info=exc_info, extra=extra)
    
    def fatal(self, message: str, **context):
        """致命错误日志 - 系统崩溃：无法启动、核心组件初始化失败"""
        extra = {"context": context} if context else {}
        self.system_logger.critical(message, extra=extra)


# ============================================================================
# 工厂函数
# ============================================================================

def create_dev_logger(name: str, log_dir: Path) -> DualChannelLogger:
    """创建开发环境日志器"""
    return DualChannelLogger(name, LogConfig.dev_config(), log_dir)


def create_prod_logger(name: str, log_dir: Path) -> DualChannelLogger:
    """创建生产环境日志器"""
    return DualChannelLogger(name, LogConfig.prod_config(), log_dir)


def create_logger_for_env(name: str, log_dir: Path, 
                           env: Environment = Environment.DEVELOPMENT) -> DualChannelLogger:
    """根据环境创建日志器"""
    return DualChannelLogger(name, LogConfig.get_config(env), log_dir)


# ============================================================================
# 统一日志管理器（单例）
# ============================================================================

class UnifiedLogManager:
    """统一日志管理器（单例）
    
    所有日志通过统一出口，支持：
    - 环境感知配置
    - 双格式输出（文本 + JSON可选）
    - 自动清理过期日志
    - 分级输出：文件DEBUG+，控制台INFO+
    """
    
    _instance: Optional['UnifiedLogManager'] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def setup(self, log_level: str = "INFO", log_dir: Optional[Path] = None) -> Path:
        """设置日志系统
        
        Args:
            log_level: 日志级别
            log_dir: 日志目录（可选，默认自动确定）
            
        Returns:
            日志文件路径
        """
        # 允许通过环境变量覆盖
        env_level = os.environ.get("WECHAT_TOOL_LOG_LEVEL", "").strip()
        if env_level:
            log_level = env_level

        console_logging_env = os.environ.get("WECHAT_TOOL_ENABLE_CONSOLE_LOG", "").strip().lower()
        wants_console = console_logging_env in {"1", "true", "yes", "on"}

        level = getattr(logging, str(log_level or "INFO").upper(), logging.INFO)

        # 确定日志目录
        if log_dir:
            self._log_dir = Path(log_dir)
        else:
            self._log_dir = self._get_log_dir()
        
        # 按日期组织日志
        now = datetime.now()
        self._log_dir = self._log_dir / str(now.year) / f"{now.month:02d}" / f"{now.day:02d}"
        
        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            import tempfile
            self._log_dir = Path(tempfile.gettempdir()) / "wechat_logs"
            self._log_dir.mkdir(parents=True, exist_ok=True)
            logging.warning(f"无法创建日志目录，已降级到 {self._log_dir}: {e}")

        # 日志文件路径
        date_str = now.strftime("%Y-%m-%d")
        self._log_file = self._log_dir / f"app_{date_str}.log"
        self._json_file = self._log_dir / f"app_{date_str}.json"

        # 检查是否已初始化且配置相同
        if self._initialized:
            if self._is_config_valid(level, wants_console):
                return self._log_file

        # 清理旧日志
        self._cleanup_old_logs(self._log_dir.parents[2])  # 回到logs根目录

        # 配置根日志器
        root_logger = logging.getLogger()
        
        # 清除现有处理器
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

        # 创建处理器
        self._setup_handlers(root_logger, level, wants_console)
        
        # 配置子日志器
        self._configure_child_loggers(level)

        # 记录启动信息
        startup_logger = logging.getLogger(__name__)
        startup_logger.info("=" * 60)
        startup_logger.info("微信解密工具日志系统初始化完成")
        startup_logger.info(f"日志文件: {self._log_file}")
        startup_logger.info(f"JSON日志: {self._json_file}")
        startup_logger.info(f"日志级别: {logging.getLevelName(level)}")
        startup_logger.info(f"进程ID: {os.getpid()}")
        startup_logger.info("=" * 60)

        self._initialized = True
        return self._log_file

    def _get_log_dir(self) -> Path:
        """获取日志目录"""
        if getattr(sys, 'frozen', False):
            # 打包后的EXE
            return Path(sys.executable).parent / 'logs'
        else:
            # 开发环境，使用项目根目录
            return Path(__file__).resolve().parents[2] / 'logs'

    def _is_config_valid(self, level: int, wants_console: bool) -> bool:
        """检查当前配置是否有效"""
        root_logger = logging.getLogger()
        if root_logger.level != level:
            return False
        
        has_file_handler = False
        has_console_handler = False
        
        for handler in root_logger.handlers:
            if isinstance(handler, logging.FileHandler):
                try:
                    if Path(handler.baseFilename).resolve() == self._log_file.resolve():
                        has_file_handler = True
                except Exception:
                    pass
            elif isinstance(handler, logging.StreamHandler):
                has_console_handler = True
        
        return has_file_handler and (has_console_handler or not wants_console)

    def _setup_handlers(self, root_logger: logging.Logger, level: int, wants_console: bool):
        """设置日志处理器"""
        # 文本文件处理器
        file_handler = logging.FileHandler(self._log_file, encoding='utf-8')
        file_handler.setFormatter(TextFormatter(include_caller=True))
        file_handler.setLevel(logging.DEBUG)
        root_logger.addHandler(file_handler)

        # JSON文件处理器（用于日志收集分析）
        json_handler = logging.FileHandler(self._json_file, encoding='utf-8')
        json_handler.setFormatter(JsonFormatter(include_caller=True, include_stack_trace=True))
        json_handler.setLevel(logging.DEBUG)
        root_logger.addHandler(json_handler)

        # 控制台处理器
        if wants_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(ColoredFormatter())
            console_handler.setLevel(max(level, logging.INFO))
            root_logger.addHandler(console_handler)

        root_logger.setLevel(level)

    def _configure_child_loggers(self, level: int):
        """配置子日志器"""
        # 配置uvicorn和fastapi日志器
        for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"]:
            logger = logging.getLogger(logger_name)
            logger.setLevel(level)
            # 移除旧的FileHandler
            for handler in logger.handlers[:]:
                if isinstance(handler, logging.FileHandler):
                    logger.removeHandler(handler)
                    try:
                        handler.close()
                    except Exception:
                        pass

    def _cleanup_old_logs(self, log_dir: Path):
        """清理超过保留天数的日志文件"""
        cutoff_date = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)

        try:
            for log_file in log_dir.rglob('app_*.log*'):
                try:
                    # 从文件名提取日期 (app_YYYY-MM-DD.log)
                    filename = log_file.stem  # app_2026-07-22
                    date_str = filename.replace('app_', '')
                    file_date = datetime.strptime(date_str, '%Y-%m-%d')

                    if file_date < cutoff_date:
                        log_file.unlink(missing_ok=True)
                except (ValueError, OSError):
                    # 文件名格式不匹配或删除失败，跳过
                    pass
        except Exception:
            # 清理失败不影响主流程
            pass

    def get_log_file(self) -> Path:
        """获取当前日志文件路径"""
        if not self._initialized:
            self.setup()
        return self._log_file

    def get_logger(self, name: str) -> logging.Logger:
        """获取指定名称的日志器"""
        return logging.getLogger(name)


# ============================================================================
# 向后兼容的WeChatLogger（代理到UnifiedLogManager）
# ============================================================================

class WeChatLogger:
    """微信解密工具统一日志管理器（向后兼容代理）
    
    内部使用UnifiedLogManager实现，保持API兼容
    """

    _instance: Optional['WeChatLogger'] = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        pass

    def setup_logging(self, log_level: str = "DEBUG") -> Path:
        """设置日志配置"""
        result = UnifiedLogManager().setup(log_level)
        WeChatLogger._initialized = True
        return result

    def get_logger(self, name: str) -> logging.Logger:
        """获取指定名称的日志器"""
        return logging.getLogger(name)

    def get_log_file_path(self) -> Path:
        """获取当前日志文件路径"""
        return UnifiedLogManager().get_log_file()


# ============================================================================
# 便捷函数（公共API）
# ============================================================================

def setup_logging(log_level: str = "INFO") -> Path:
    """设置日志配置的便捷函数"""
    return UnifiedLogManager().setup(log_level)


def get_logger(name: str) -> logging.Logger:
    """获取日志器的便捷函数"""
    manager = UnifiedLogManager()
    if not manager._initialized:
        manager.setup()
    return manager.get_logger(name)


def get_log_file_path() -> Path:
    """获取当前日志文件路径的便捷函数"""
    manager = UnifiedLogManager()
    if not manager._initialized:
        manager.setup()
    return manager.get_log_file()


def get_tn_logger(tn_module: str) -> TNLoggerAdapter:
    """获取TN模块专用日志器（兼容exe_logging）
    
    Args:
        tn_module: TN模块名称（如 TN-01, TN-02）
        
    Returns:
        带TN标签的Logger适配器
    """
    if not UnifiedLogManager._initialized:
        setup_logging()
    logger = logging.getLogger(f'wechat.{tn_module}')
    return TNLoggerAdapter(logger, {'tn_module': tn_module})


# ============================================================================
# 健康监控器 - 模块1异常指标监控
# ============================================================================

from collections import defaultdict
import threading


class HealthStatus(Enum):
    """健康状态枚举"""
    NORMAL = "normal"        # 正常运行
    WARNING = "warning"      # 警告（接近阈值）
    ABNORMAL = "abnormal"    # 异常（需要开启DEBUG）


class HealthMonitor:
    """健康监控器 - 检测模块1异常指标
    
    监控场景：
    - 密钥获取状态
    - 数据库定位正确性
    - 数据采集监听状态
    - 消息数据反馈
    - 消息实时性
    
    触发条件：
    - 错误率超阈值
    - 持续异常告警
    - 偶现难以复现故障
    """
    
    # 阈值配置 - 根据用户需求定义
    THRESHOLDS = {
        'key_acquire_fail': 3,           # 密钥获取连续失败次数
        'db_location_fail': 2,           # 数据库定位失败次数
        'monitor_exit': 1,               # 监听进程异常退出次数
        'msg_parse_fail_rate': 0.10,     # 消息解析失败率 (10%)
        'msg_delay_count': 3,            # 消息延迟计数
        'msg_delay_threshold': 30,       # 消息延迟阈值(秒)
        'error_rate_per_min': 5,         # 每分钟错误率阈值
        'consecutive_failures': 3,       # 连续失败次数
    }
    
    # 检测窗口（秒）
    WINDOWS = {
        'key_acquire': 300,              # 密钥获取: 5分钟
        'db_location': 180,              # 数据库定位: 3分钟
        'monitor_exit': 0,               # 监听退出: 即时
        'msg_parse': 60,                 # 消息解析: 1分钟
        'msg_delay': 60,                 # 消息延迟: 1分钟
        'error_rate': 60,                # 错误率: 1分钟
    }
    
    # 异常类型到模块的映射
    ERROR_MODULE_MAPPING = {
        'key_acquire_fail': 'wechat_core.key',
        'db_location_fail': 'wechat_core.db',
        'monitor_exit': 'wechat_core.monitor',
        'msg_parse_fail': 'wechat_core.parser',
        'msg_delay': 'wechat_core.polling',
    }
    
    def __init__(self):
        self._error_events: Dict[str, List[datetime]] = defaultdict(list)
        self._status: HealthStatus = HealthStatus.NORMAL
        self._abnormal_modules: Set[str] = set()
        self._lock = threading.Lock()
        self._total_operations: Dict[str, int] = defaultdict(int)  # 总操作数（用于计算失败率）
        self._consecutive_failures: Dict[str, int] = defaultdict(int)  # 连续失败计数
        
    def record_error(self, error_type: str, module: str = None, 
                     details: dict = None) -> bool:
        """记录错误事件
        
        Args:
            error_type: 错误类型（key_acquire_fail等）
            module: 模块名（可选，自动映射）
            details: 错误详情
            
        Returns:
            是否触发异常阈值
        """
        with self._lock:
            now = datetime.now()
            
            # 自动映射模块
            if module is None:
                module = self.ERROR_MODULE_MAPPING.get(error_type, 'unknown')
            
            # 记录错误时间
            event_key = f"{module}:{error_type}"
            self._error_events[event_key].append(now)
            
            # 增加连续失败计数
            self._consecutive_failures[event_key] += 1
            
            # 清理过期事件（滑动窗口）
            self._cleanup_expired_events(event_key, now)
            
            # 检查是否触发阈值
            triggered = self._check_threshold(error_type, event_key)
            
            if triggered:
                self._status = HealthStatus.ABNORMAL
                self._abnormal_modules.add(module)
                
            return triggered
    
    def record_success(self, error_type: str, module: str = None):
        """记录成功事件（重置连续失败计数，用于计算失败率）
        
        Args:
            error_type: 操作类型
            module: 模块名
        """
        with self._lock:
            if module is None:
                module = self.ERROR_MODULE_MAPPING.get(error_type, 'unknown')
            
            event_key = f"{module}:{error_type}"
            
            # 重置连续失败计数
            self._consecutive_failures[event_key] = 0
            
            # 增加总操作数
            self._total_operations[event_key] += 1
            
            # 如果模块恢复正常，从异常集合中移除
            if module in self._abnormal_modules:
                if self._consecutive_failures[event_key] == 0:
                    self._abnormal_modules.discard(module)
                    self._update_overall_status()
    
    def _cleanup_expired_events(self, event_key: str, now: datetime):
        """清理过期事件（滑动窗口）"""
        # 获取对应的检测窗口
        error_type = event_key.split(':')[-1] if ':' in event_key else event_key
        window_seconds = self.WINDOWS.get(error_type, 60)
        
        if window_seconds > 0:
            cutoff = now - timedelta(seconds=window_seconds)
            self._error_events[event_key] = [
                t for t in self._error_events[event_key] if t > cutoff
            ]
    
    def _check_threshold(self, error_type: str, event_key: str) -> bool:
        """检查是否触发阈值"""
        threshold = self.THRESHOLDS.get(error_type, 5)
        
        # 检查连续失败次数
        consecutive = self._consecutive_failures.get(event_key, 0)
        if consecutive >= self.THRESHOLDS.get('consecutive_failures', 3):
            return True
        
        # 检查窗口内错误数
        error_count = len(self._error_events.get(event_key, []))
        
        if error_type == 'msg_parse_fail_rate':
            # 失败率检查
            total = self._total_operations.get(event_key, 1)
            if total > 0 and error_count / total >= threshold:
                return True
        else:
            # 绝对次数检查
            if error_count >= threshold:
                return True
                
        return False
    
    def _update_overall_status(self):
        """更新整体状态"""
        if not self._abnormal_modules:
            self._status = HealthStatus.NORMAL
        else:
            self._status = HealthStatus.ABNORMAL
    
    def check_health(self) -> HealthStatus:
        """检查系统健康状态"""
        with self._lock:
            # 清理所有过期事件
            now = datetime.now()
            for event_key in list(self._error_events.keys()):
                self._cleanup_expired_events(event_key, now)
            
            # 更新状态
            self._update_overall_status()
            
            return self._status
    
    def is_module_healthy(self, module: str) -> bool:
        """检查指定模块是否健康
        
        恢复判定条件：
        - 异常指标（错误率）持续低于阈值
        - 流程正常运行
        - 无持续同类告警
        """
        with self._lock:
            # 检查模块是否在异常列表中
            if module not in self._abnormal_modules:
                return True
            
            # 检查模块相关的连续失败是否已清零
            for event_key, count in self._consecutive_failures.items():
                if event_key.startswith(f"{module}:"):
                    if count > 0:
                        return False
            
            # 检查窗口内是否还有错误
            now = datetime.now()
            for event_key, events in self._error_events.items():
                if event_key.startswith(f"{module}:"):
                    self._cleanup_expired_events(event_key, now)
                    if events:  # 窗口内还有错误
                        return False
            
            return True
    
    def get_abnormal_modules(self) -> Set[str]:
        """获取异常模块列表"""
        with self._lock:
            return self._abnormal_modules.copy()
    
    def get_error_stats(self) -> dict:
        """获取错误统计信息"""
        with self._lock:
            now = datetime.now()
            stats = {
                'status': self._status.value,
                'abnormal_modules': list(self._abnormal_modules),
                'error_counts': {},
                'consecutive_failures': {}
            }
            
            for event_key, events in self._error_events.items():
                self._cleanup_expired_events(event_key, now)
                stats['error_counts'][event_key] = len(events)
            
            for event_key, count in self._consecutive_failures.items():
                stats['consecutive_failures'][event_key] = count
                
            return stats
    
    def reset(self):
        """重置监控器状态"""
        with self._lock:
            self._error_events.clear()
            self._abnormal_modules.clear()
            self._total_operations.clear()
            self._consecutive_failures.clear()
            self._status = HealthStatus.NORMAL


# ============================================================================
# 动态日志级别管理器（热切换）
# ============================================================================

class DynamicLogLevelManager:
    """动态日志级别管理器（热切换）
    
    运行机制：
    1. 接收HealthMonitor的异常信号
    2. 针对异常模块开启DEBUG（不是全量DEBUG）
    3. 启动后台定时器监控
    4. 定期检查健康状态
    5. 恢复正常后自动降级
    
    使用方式：
    - 手动触发：set_temporary_level()
    - 自动触发：配合 HealthMonitor 使用
    - 环境变量：WECHAT_TOOL_TEMP_DEBUG=DEBUG,10
    """
    
    _instance: Optional['DynamicLogLevelManager'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._health_monitor: Optional[HealthMonitor] = None
        self._module_levels: Dict[str, Tuple[int, datetime, str]] = {}  # 模块 -> (临时级别, 恢复时间, 原因)
        self._original_levels: Dict[str, int] = {}  # 模块 -> 原始级别
        self._check_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._check_interval: int = 60  # 检查间隔（秒）
        self._initialized = True
        
    def set_health_monitor(self, monitor: HealthMonitor):
        """设置健康监控器"""
        self._health_monitor = monitor
        
    def set_temporary_level(self, level: str, module: str = None, 
                            duration: int = 10, reason: str = "") -> bool:
        """临时设置日志级别（模块级）
        
        Args:
            level: 目标级别（DEBUG/INFO/WARN/ERROR）
            module: 指定模块（如 "wechat_core.key"），None表示全局
            duration: 持续时间（分钟），默认10分钟
            reason: 触发原因
            
        Returns:
            是否设置成功
        """
        with self._lock:
            target_level = getattr(logging, level.upper(), logging.DEBUG)
            restore_time = datetime.now() + timedelta(minutes=duration)
            
            if module:
                # 模块级调整
                return self._set_module_level(module, target_level, restore_time, reason)
            else:
                # 全局调整（谨慎使用）
                return self._set_global_level(target_level, restore_time, reason)
    
    def _set_module_level(self, module: str, level: int, 
                          restore_time: datetime, reason: str) -> bool:
        """设置模块级日志级别"""
        try:
            logger = logging.getLogger(module)
            
            # 保存原始级别
            if module not in self._original_levels:
                self._original_levels[module] = logger.level or logging.INFO
            
            # 设置新级别
            logger.setLevel(level)
            
            # 记录临时状态
            self._module_levels[module] = (level, restore_time, reason)
            
            # 记录日志
            logging.info(
                f"[DynamicLogLevel] 模块 [{module}] 日志级别已临时调整为 "
                f"{logging.getLevelName(level)}，将在 {restore_time.strftime('%H:%M:%S')} 检查恢复。"
                f"原因: {reason or '手动触发'}"
            )
            
            # 启动后台检查定时器
            self._start_check_timer()
            
            return True
            
        except Exception as e:
            logging.error(f"[DynamicLogLevel] 设置模块 [{module}] 日志级别失败: {e}")
            return False
    
    def _set_global_level(self, level: int, restore_time: datetime, reason: str) -> bool:
        """设置全局日志级别"""
        try:
            root_logger = logging.getLogger()
            
            # 保存原始级别
            if 'root' not in self._original_levels:
                self._original_levels['root'] = root_logger.level or logging.INFO
            
            # 设置根日志器级别
            root_logger.setLevel(level)
            
            # 设置所有子日志器级别
            for name, logger in logging.Logger.manager.loggerDict.items():
                if isinstance(logger, logging.Logger):
                    if name not in self._original_levels:
                        self._original_levels[name] = logger.level or logging.INFO
                    logger.setLevel(level)
            
            # 记录临时状态
            self._module_levels['root'] = (level, restore_time, reason)
            
            logging.info(
                f"[DynamicLogLevel] 全局日志级别已临时调整为 "
                f"{logging.getLevelName(level)}，将在 {restore_time.strftime('%H:%M:%S')} 检查恢复。"
                f"原因: {reason or '手动触发'}"
            )
            
            self._start_check_timer()
            
            return True
            
        except Exception as e:
            logging.error(f"[DynamicLogLevel] 设置全局日志级别失败: {e}")
            return False
    
    def _start_check_timer(self):
        """启动后台检查定时器"""
        if self._check_timer is not None:
            try:
                self._check_timer.cancel()
            except Exception:
                pass
        
        self._check_timer = threading.Timer(
            self._check_interval,
            self._check_and_restore
        )
        self._check_timer.daemon = True
        self._check_timer.start()
    
    def check_and_restore(self):
        """检查并恢复正常的模块（公共接口）"""
        self._check_and_restore()
    
    def _check_and_restore(self):
        """检查并恢复正常的模块
        
        恢复判定条件：
        - 异常指标（错误率）持续低于阈值
        - 流程正常运行
        - 无持续同类告警
        """
        with self._lock:
            now = datetime.now()
            restored_modules = []
            extended_modules = []
            
            for module, (level, restore_time, reason) in list(self._module_levels.items()):
                # 检查是否到达恢复检查时间
                if now >= restore_time:
                    # 检查健康状态
                    should_restore = True
                    
                    if self._health_monitor and module != 'root':
                        should_restore = self._health_monitor.is_module_healthy(module)
                    
                    if should_restore:
                        # 恢复原始级别
                        original = self._original_levels.get(module, logging.INFO)
                        
                        if module == 'root':
                            logging.getLogger().setLevel(original)
                            for name, logger in logging.Logger.manager.loggerDict.items():
                                if isinstance(logger, logging.Logger) and name in self._original_levels:
                                    logger.setLevel(self._original_levels[name])
                        else:
                            logging.getLogger(module).setLevel(original)
                        
                        del self._module_levels[module]
                        restored_modules.append(module)
                        
                        logging.info(
                            f"[DynamicLogLevel] 模块 [{module}] 日志级别已恢复为 "
                            f"{logging.getLevelName(original)}"
                        )
                    else:
                        # 延长DEBUG时间
                        new_restore_time = now + timedelta(minutes=5)
                        self._module_levels[module] = (level, new_restore_time, reason)
                        extended_modules.append(module)
                        
                        logging.info(
                            f"[DynamicLogLevel] 模块 [{module}] 仍存在异常，"
                            f"DEBUG延长至 {new_restore_time.strftime('%H:%M:%S')}"
                        )
            
            # 如果还有模块在临时状态，继续定时检查
            if self._module_levels:
                self._start_check_timer()
    
    def restore_level(self, module: str = None):
        """手动恢复日志级别
        
        Args:
            module: 指定模块，None表示恢复所有
        """
        with self._lock:
            if module:
                if module in self._module_levels:
                    original = self._original_levels.get(module, logging.INFO)
                    logging.getLogger(module).setLevel(original)
                    del self._module_levels[module]
                    logging.info(f"[DynamicLogLevel] 模块 [{module}] 日志级别已手动恢复")
            else:
                # 恢复所有
                for mod in list(self._module_levels.keys()):
                    original = self._original_levels.get(mod, logging.INFO)
                    if mod == 'root':
                        logging.getLogger().setLevel(original)
                    else:
                        logging.getLogger(mod).setLevel(original)
                
                self._module_levels.clear()
                logging.info("[DynamicLogLevel] 所有模块日志级别已手动恢复")
    
    def get_status(self) -> dict:
        """获取当前状态"""
        with self._lock:
            now = datetime.now()
            status = {
                'modules_in_debug': [],
                'total_modules': len(self._module_levels),
                'health_status': self._health_monitor.check_health().value if self._health_monitor else 'unknown'
            }
            
            for module, (level, restore_time, reason) in self._module_levels.items():
                remaining = (restore_time - now).total_seconds()
                status['modules_in_debug'].append({
                    'module': module,
                    'level': logging.getLevelName(level),
                    'restore_time': restore_time.isoformat(),
                    'remaining_seconds': max(0, remaining),
                    'reason': reason
                })
            
            return status
    
    def check_environment_trigger(self):
        """检查环境变量触发
        
        环境变量格式：
        WECHAT_TOOL_TEMP_DEBUG=DEBUG,10
        表示：开启DEBUG级别，持续10分钟
        """
        env_value = os.environ.get('WECHAT_TOOL_TEMP_DEBUG', '').strip()
        
        if env_value:
            parts = env_value.split(',')
            level = parts[0].upper() if parts else 'DEBUG'
            duration = int(parts[1]) if len(parts) > 1 else 10
            
            self.set_temporary_level(
                level=level,
                module=None,  # 全局
                duration=duration,
                reason="环境变量触发"
            )
            
            # 清除环境变量，避免重复触发
            del os.environ['WECHAT_TOOL_TEMP_DEBUG']


# ============================================================================
# 采样日志处理器
# ============================================================================

class SamplingHandler(logging.Handler):
    """采样日志处理器 - 高频操作日志采样
    
    根据变更提案：
    - 每100次只记录1次INFO（sample_rate=0.01）
    - ERROR全量记录
    """
    
    def __init__(self, sample_rate: float = 0.01, 
                 min_level: int = logging.INFO,
                 target_handler: logging.Handler = None):
        """
        Args:
            sample_rate: 采样率（0.01 = 1%）
            min_level: 最低采样级别（INFO及以下采样，ERROR全量）
            target_handler: 目标处理器（默认使用控制台）
        """
        super().__init__()
        self.sample_rate = sample_rate
        self.min_level = min_level
        self.target_handler = target_handler or logging.StreamHandler()
        self._counter = 0
        self._lock = threading.Lock()
        
    def emit(self, record):
        """发送日志记录"""
        # ERROR及以上全量记录
        if record.levelno >= logging.ERROR:
            self.target_handler.emit(record)
            return
        
        # 低于采样级别的日志不记录
        if record.levelno < self.min_level:
            return
        
        # 采样逻辑
        with self._lock:
            self._counter += 1
            # 每N次记录一次
            if self.sample_rate > 0:
                n = int(1 / self.sample_rate)
                if self._counter % n == 0:
                    self.target_handler.emit(record)


# ============================================================================
# 便捷函数扩展
# ============================================================================

def get_health_monitor() -> HealthMonitor:
    """获取健康监控器单例"""
    return HealthMonitor()


def get_dynamic_log_manager() -> DynamicLogLevelManager:
    """获取动态日志级别管理器单例"""
    return DynamicLogLevelManager()


def trigger_debug_for_module(module: str, duration: int = 10, reason: str = ""):
    """触发模块DEBUG模式（便捷函数）
    
    Args:
        module: 模块名（如 "wechat_core.key"）
        duration: 持续时间（分钟）
        reason: 触发原因
    """
    manager = DynamicLogLevelManager()
    manager.set_temporary_level('DEBUG', module=module, duration=duration, reason=reason)


def record_error_for_monitoring(error_type: str, module: str = None, details: dict = None) -> bool:
    """记录错误到健康监控器（便捷函数）
    
    Args:
        error_type: 错误类型
        module: 模块名
        details: 错误详情
        
    Returns:
        是否触发异常阈值
    """
    monitor = HealthMonitor()
    return monitor.record_error(error_type, module, details)


# ============================================================================
# 导出公共API
# ============================================================================

__all__ = [
    # 环境感知配置
    'Environment',
    'LogConfig',
    # 双通道日志器
    'DualChannelLogger',
    # 工厂函数
    'create_dev_logger',
    'create_prod_logger',
    'create_logger_for_env',
    # 统一日志API
    'UnifiedLogManager',
    'WeChatLogger',
    'setup_logging',
    'get_logger',
    'get_log_file_path',
    'get_tn_logger',
    # 格式化器（供高级用户使用）
    'TextFormatter',
    'JsonFormatter',
    'ColoredFormatter',
    'ConsoleFormatter',
    # 常量
    'LOG_COLORS',
    'LOG_RETENTION_DAYS',
    # 健康监控器
    'HealthStatus',
    'HealthMonitor',
    # 动态日志级别管理器
    'DynamicLogLevelManager',
    # 采样日志处理器
    'SamplingHandler',
    # 便捷函数
    'get_health_monitor',
    'get_dynamic_log_manager',
    'trigger_debug_for_module',
    'record_error_for_monitoring',
]
