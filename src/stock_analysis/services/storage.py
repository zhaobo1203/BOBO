"""
匹配结果存储与增量更新服务
将匹配结果存入stock_mentions.db，支持全量和增量更新
"""
import sqlite3
import logging
from datetime import datetime
from typing import List, Optional

from ..config.settings import STOCK_MENTIONS_DB_PATH, MESSAGES_DB_PATH
from ..models.mention import MentionRecord

logger = logging.getLogger(__name__)


class StorageService:
    """匹配结果存储服务"""

    def __init__(self, db_path: str = None, messages_db_path: str = None):
        self.db_path = db_path or str(STOCK_MENTIONS_DB_PATH)
        self.messages_db_path = messages_db_path or str(MESSAGES_DB_PATH)
        self._last_processed_id: int = 0
        self._init_db()

    def _init_db(self):
        """初始化数据库，创建表结构"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_mentions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT NOT NULL,
                match_type TEXT NOT NULL,
                sender TEXT NOT NULL,
                message_content TEXT NOT NULL,
                send_time TEXT NOT NULL,
                group_name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_stock_code
            ON stock_mentions(stock_code)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_send_time
            ON stock_mentions(send_time)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_message_id
            ON stock_mentions(message_id)
        """)

        # 记录处理进度的表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS process_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                process_type TEXT NOT NULL,
                last_message_id INTEGER DEFAULT 0,
                total_processed INTEGER DEFAULT 0,
                total_matched INTEGER DEFAULT 0,
                process_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()
        logger.info(f"存储数据库初始化完成: {self.db_path}")

    def save_mentions(self, mentions: List[MentionRecord], process_type: str = "full") -> int:
        """
        保存匹配结果到数据库

        Args:
            mentions: 提及记录列表
            process_type: 处理类型 full/incremental

        Returns:
            保存的记录数
        """
        if not mentions:
            logger.info("无匹配结果需要保存")
            return 0

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        saved_count = 0
        for m in mentions:
            try:
                cursor.execute("""
                    INSERT INTO stock_mentions
                    (message_id, stock_code, stock_name, match_type,
                     sender, message_content, send_time, group_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    m.message_id, m.stock_code, m.stock_name, m.match_type,
                    m.sender, m.message_content, m.send_time, m.group_name,
                ))
                saved_count += 1
            except Exception as e:
                logger.error(f"保存提及记录失败: {e}, message_id={m.message_id}")

        # 记录处理日志
        last_msg_id = max((m.message_id for m in mentions), default=0)
        cursor.execute("""
            INSERT INTO process_log
            (process_type, last_message_id, total_processed, total_matched)
            VALUES (?, ?, ?, ?)
        """, (process_type, last_msg_id, 0, saved_count))

        conn.commit()
        conn.close()

        logger.info(f"保存{saved_count}条提及记录, 处理类型={process_type}")
        return saved_count

    def get_all_mentions(self) -> List[MentionRecord]:
        """获取所有提及记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, message_id, stock_code, stock_name, match_type,
                   sender, message_content, send_time, group_name
            FROM stock_mentions
            ORDER BY send_time
        """)
        rows = cursor.fetchall()
        conn.close()

        mentions = []
        for row in rows:
            mentions.append(MentionRecord(
                id=row[0],
                message_id=row[1],
                stock_code=row[2],
                stock_name=row[3],
                match_type=row[4],
                sender=row[5],
                message_content=row[6],
                send_time=row[7],
                group_name=row[8],
            ))

        logger.info(f"从数据库加载{len(mentions)}条提及记录")
        return mentions

    def get_last_processed_id(self) -> int:
        """获取最后处理的消息ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT MAX(last_message_id) FROM process_log
        """)
        result = cursor.fetchone()
        conn.close()

        last_id = result[0] if result and result[0] else 0
        self._last_processed_id = last_id
        return last_id

    def get_new_messages(self) -> List[tuple]:
        """
        从messages.db获取未处理的新消息

        Returns:
            消息元组列表 (id, sender_nickname, message_content, send_time, group_name)
        """
        last_id = self.get_last_processed_id()

        conn = sqlite3.connect(self.messages_db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, sender_nickname, message_content, send_time, group_name
            FROM group_messages
            WHERE id > ?
            ORDER BY id
        """, (last_id,))
        rows = cursor.fetchall()
        conn.close()

        logger.info(f"发现{len(rows)}条新消息(已处理至ID={last_id})")
        return rows

    def get_all_messages(self) -> List[tuple]:
        """
        从messages.db获取所有消息

        Returns:
            消息元组列表 (id, sender_nickname, message_content, send_time, group_name)
        """
        conn = sqlite3.connect(self.messages_db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, sender_nickname, message_content, send_time, group_name
            FROM group_messages
            ORDER BY id
        """)
        rows = cursor.fetchall()
        conn.close()

        logger.info(f"从消息数据库加载{len(rows)}条消息")
        return rows

    def clear_all(self):
        """清空所有匹配结果（用于全量重新匹配）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM stock_mentions")
        cursor.execute("DELETE FROM process_log")
        conn.commit()
        conn.close()
        self._last_processed_id = 0
        logger.info("已清空所有匹配结果")