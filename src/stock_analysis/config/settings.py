"""
模块3配置文件
"""
import os
from pathlib import Path

# 项目根目录（WeChatDataAnalysis/）
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# 数据库路径
A_STOCK_DB_PATH = PROJECT_ROOT / "data" / "a_stock_db" / "a_stock.db"
MESSAGES_DB_PATH = PROJECT_ROOT / "data" / "messages.db"
STOCK_MENTIONS_DB_PATH = PROJECT_ROOT / "data" / "stock_mentions.db"

# 日志目录
LOG_DIR = PROJECT_ROOT / "logs"

# FastAPI服务配置
API_HOST = "0.0.0.0"
API_PORT = 8000

# 增量更新间隔（秒）
INCREMENTAL_UPDATE_INTERVAL = 60  # 60秒（避免频繁刷新导致卡顿）

# A股数据过滤规则
EXCLUDE_NAME_PATTERNS = ["指数", "退市"]

# 消息过滤规则
# 加密数据特征：以十六进制字符开头且长度超过100
ENCRYPTED_DATA_MIN_LENGTH = 100
# XML消息特征
XML_START_MARKERS = ["<?xml", "<msg>", "<appmsg"]
# 黑名单配置文件路径
BLACKLIST_PATH = Path(__file__).parent / "blacklist.json"

# 发送人前缀正则（如 "leijian8981:\n"）
SENDER_PREFIX_PATTERN = r"^[a-zA-Z0-9_]+:\n"
