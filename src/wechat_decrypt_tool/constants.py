"""统一错误码和常量定义模块

按照 TECHNICAL_SPECIFICATION_REPORT.md 规格定义的错误码和业务常量。
"""

from typing import Dict


# ============================================================
# 错误码定义
# ============================================================

class ErrorCode:
    """统一错误码定义

    按技术规格报告定义的错误码：
    - ERR_PROC_*: 进程管理 (TN-01)
    - ERR_ACCOUNT_*: 账号检测 (TN-02)
    - ERR_KEY_*: 密钥获取 (TN-03)
    - ERR_DECRYPT_*: 数据库解密 (TN-04)
    - ERR_WCDB_*: 实时监听 (TN-05)
    - ERR_MSG_*: 消息处理 (TN-06)
    """

    # TN-01: 进程管理
    ERR_PROC_001 = "微信进程不存在"
    ERR_PROC_002 = "无法终止微信进程"
    ERR_PROC_003 = "微信安装路径未找到"
    ERR_PROC_004 = "微信启动失败"

    # TN-02: 账号检测
    ERR_ACCOUNT_001 = "无微信进程运行"
    ERR_ACCOUNT_002 = "无法获取文件句柄"
    ERR_ACCOUNT_003 = "数据目录不存在"
    ERR_ACCOUNT_004 = "账号ID格式错误"

    # TN-03: 密钥获取
    ERR_KEY_001 = "进程不存在"
    ERR_KEY_002 = "内存扫描失败"
    ERR_KEY_003 = "密钥验证失败"
    ERR_KEY_004 = "Hook注入失败"
    ERR_KEY_005 = "wx_key模块不可用"

    # TN-04: 数据库解密
    ERR_DECRYPT_001 = "密钥格式错误"
    ERR_DECRYPT_002 = "数据库文件不存在"
    ERR_DECRYPT_003 = "解密失败（密钥错误）"
    ERR_DECRYPT_004 = "写入文件失败"
    ERR_DECRYPT_005 = "数据库损坏"

    # TN-05: 实时监听
    ERR_WCDB_001 = "数据库文件不存在"
    ERR_WCDB_002 = "密钥错误"
    ERR_WCDB_003 = "Sidecar启动失败"
    ERR_WCDB_004 = "无效句柄"
    ERR_WCDB_005 = "会话不存在"
    ERR_WCDB_006 = "连接超时"

    # TN-06: 消息处理
    ERR_MSG_001 = "消息内容解码失败"
    ERR_MSG_002 = "发送者信息获取失败"
    ERR_MSG_003 = "消息存储失败"


# ============================================================
# 进程管理常量
# ============================================================

WECHAT_PROCESS_NAMES = ['weixin.exe', 'wechat.exe']
PROCESS_WAIT_TIMEOUT = 30  # 秒


# ============================================================
# 密钥获取常量
# ============================================================

KEY_LENGTH = 64  # 十六进制字符数
KEY_LENGTH_BYTES = 32  # 字节数
PBKDF2_ITERATIONS = 256000  # 迭代次数


# ============================================================
# 数据库解密常量
# ============================================================

PAGE_SIZE = 4096  # 字节
IV_SIZE = 16  # 字节
HMAC_SIZE = 64  # 字节
SALT_SIZE = 16  # 字节
RESERVE_SIZE = IV_SIZE + HMAC_SIZE  # 80 字节


# ============================================================
# 消息监听常量
# ============================================================

POLL_INTERVAL_MIN = 0.5  # 秒
POLL_INTERVAL_MAX = 5.0  # 秒
POLL_INTERVAL_DEFAULT = 1.0  # 秒
RECONNECT_INTERVAL = 60  # 秒


# ============================================================
# 消息存储常量
# ============================================================

MAX_MESSAGE_LENGTH = 10000  # 字符
MAX_SENDER_NAME_LENGTH = 100  # 字符


# ============================================================
# 日志配置常量
# ============================================================

LOG_MAX_SIZE = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 5


# ============================================================
# 文件路径常量
# ============================================================

# 注册表路径
REGISTRY_PATHS = [
    ("HKEY_CURRENT_USER", r"Software\Tencent\WeChat"),
    ("HKEY_CURRENT_USER", r"Software\Tencent\Weixin"),
    ("HKEY_LOCAL_MACHINE", r"SOFTWARE\Tencent\WeChat"),
    ("HKEY_LOCAL_MACHINE", r"SOFTWARE\WOW6432Node\Tencent\WeChat"),
]

# 常见安装路径
COMMON_INSTALL_PATHS = [
    r"%PROGRAMFILES%\Tencent\WeChat\WeChat.exe",
    r"%PROGRAMFILES(X86)%\Tencent\WeChat\WeChat.exe",
]

# 数据目录候选
DATA_DIR_CANDIDATES = [
    r"%USERPROFILE%\Documents\WeChat Files",
    r"%USERPROFILE%\Documents\xwechat_files",
    r"D:\xwechat_files",
    r"E:\xwechat_files",
]


# ============================================================
# 日志埋点事件
# ============================================================

LOG_EVENTS = {
    # 进程管理
    "PROC_DETECT": "进程检测",
    "PROC_KILL": "进程终止",
    "PROC_LAUNCH": "微信启动",

    # 账号检测
    "ACCOUNT_DETECT": "账号检测",
    "ACCOUNT_MATCH": "账号匹配",

    # 密钥获取
    "KEY_LOAD": "密钥加载",
    "KEY_SCAN": "内存扫描",
    "KEY_HOOK": "Hook注入",

    # 数据库解密
    "DB_DECRYPT": "数据库解密",
    "DB_VERIFY": "解密验证",

    # 消息监听
    "MSG_POLL": "消息轮询",
    "MSG_NEW": "新消息",
    "MSG_SAVE": "消息存储",
}


# ============================================================
# ZSTD压缩常量
# ============================================================

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"  # zstd魔数
