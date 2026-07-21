"""群消息存储模块

提供群消息的持久化存储功能，将监听到的消息保存到 SQLite 数据库。
"""

import sqlite3
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from .logging_config import get_logger

logger = get_logger(__name__)

# 默认数据库路径
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "messages.db"


class MessageStorage:
    """群消息存储管理器"""

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化消息存储

        Args:
            db_path: 数据库文件路径，默认为 data/messages.db
        """
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._ensure_database()

    def _ensure_database(self) -> None:
        """确保数据库和表存在"""
        # 确保目录存在
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # 创建表
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS group_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_nickname TEXT NOT NULL,
                    message_content TEXT NOT NULL,
                    send_time DATETIME NOT NULL,
                    group_name TEXT NOT NULL,
                    group_id TEXT,
                    sender_id TEXT,
                    message_type INTEGER DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 创建索引以优化查询
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_send_time
                ON group_messages(send_time)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_group_name
                ON group_messages(group_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_group_id
                ON group_messages(group_id)
            """)

            conn.commit()

        logger.info(f"消息存储数据库已初始化: {self.db_path}")

    @contextmanager
    def _get_connection(self):
        """获取数据库连接的上下文管理器"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def save_message(
        self,
        sender_nickname: str,
        message_content: str,
        send_time: datetime,
        group_name: str,
        group_id: Optional[str] = None,
        sender_id: Optional[str] = None,
        message_type: int = 1
    ) -> int:
        """
        保存一条消息

        Args:
            sender_nickname: 发送者昵称
            message_content: 消息内容
            send_time: 发送时间
            group_name: 群名称
            group_id: 群ID（可选）
            sender_id: 发送者ID（可选）
            message_type: 消息类型（默认1为文字消息）

        Returns:
            插入的记录ID
        """
        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO group_messages
                (sender_nickname, message_content, send_time, group_name, group_id, sender_id, message_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                sender_nickname,
                message_content,
                send_time.strftime('%Y-%m-%d %H:%M:%S'),
                group_name,
                group_id,
                sender_id,
                message_type
            ))
            conn.commit()
            record_id = cursor.lastrowid

        logger.debug(f"已保存消息: [{group_name}] {sender_nickname}: {message_content[:50]}...")
        return record_id

    def save_message_batch(self, messages: List[Dict[str, Any]]) -> int:
        """
        批量保存消息

        Args:
            messages: 消息列表，每个消息为字典格式

        Returns:
            成功保存的消息数量
        """
        saved_count = 0
        with self._get_connection() as conn:
            for msg in messages:
                try:
                    send_time = msg.get('send_time')
                    if isinstance(send_time, str):
                        send_time = datetime.strptime(send_time, '%Y-%m-%d %H:%M:%S')
                    elif isinstance(send_time, (int, float)):
                        send_time = datetime.fromtimestamp(send_time)

                    conn.execute("""
                        INSERT INTO group_messages
                        (sender_nickname, message_content, send_time, group_name, group_id, sender_id, message_type)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        msg.get('sender_nickname', '未知'),
                        msg.get('message_content', ''),
                        send_time.strftime('%Y-%m-%d %H:%M:%S') if send_time else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        msg.get('group_name', '未知群'),
                        msg.get('group_id'),
                        msg.get('sender_id'),
                        msg.get('message_type', 1)
                    ))
                    saved_count += 1
                except Exception as e:
                    logger.warning(f"保存消息失败: {e}")

            conn.commit()

        logger.info(f"批量保存了 {saved_count} 条消息")
        return saved_count

    def get_messages(
        self,
        group_name: Optional[str] = None,
        group_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        查询消息

        Args:
            group_name: 群名称（可选，支持模糊匹配）
            group_id: 群ID（可选）
            start_time: 开始时间（可选）
            end_time: 结束时间（可选）
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            消息列表
        """
        query = "SELECT * FROM group_messages WHERE 1=1"
        params = []

        if group_name:
            query += " AND group_name LIKE ?"
            params.append(f"%{group_name}%")

        if group_id:
            query += " AND group_id = ?"
            params.append(group_id)

        if start_time:
            query += " AND send_time >= ?"
            params.append(start_time.strftime('%Y-%m-%d %H:%M:%S'))

        if end_time:
            query += " AND send_time <= ?"
            params.append(end_time.strftime('%Y-%m-%d %H:%M:%S'))

        query += " ORDER BY send_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        return [dict(row) for row in rows]

    def get_message_count(
        self,
        group_name: Optional[str] = None,
        group_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> int:
        """
        获取消息数量

        Args:
            group_name: 群名称（可选）
            group_id: 群ID（可选）
            start_time: 开始时间（可选）
            end_time: 结束时间（可选）

        Returns:
            消息数量
        """
        query = "SELECT COUNT(*) FROM group_messages WHERE 1=1"
        params = []

        if group_name:
            query += " AND group_name LIKE ?"
            params.append(f"%{group_name}%")

        if group_id:
            query += " AND group_id = ?"
            params.append(group_id)

        if start_time:
            query += " AND send_time >= ?"
            params.append(start_time.strftime('%Y-%m-%d %H:%M:%S'))

        if end_time:
            query += " AND send_time <= ?"
            params.append(end_time.strftime('%Y-%m-%d %H:%M:%S'))

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            count = cursor.fetchone()[0]

        return count

    def get_groups(self) -> List[Dict[str, Any]]:
        """
        获取所有已存储消息的群聊列表

        Returns:
            群聊列表，包含群名称、群ID、消息数量等
        """
        query = """
            SELECT
                group_name,
                group_id,
                COUNT(*) as message_count,
                MAX(send_time) as last_message_time
            FROM group_messages
            GROUP BY group_name, group_id
            ORDER BY last_message_time DESC
        """

        with self._get_connection() as conn:
            cursor = conn.execute(query)
            rows = cursor.fetchall()

        return [dict(row) for row in rows]

    def clear_messages(
        self,
        group_name: Optional[str] = None,
        before_time: Optional[datetime] = None
    ) -> int:
        """
        清理消息

        Args:
            group_name: 群名称（可选，不指定则清理所有）
            before_time: 清理此时间之前的消息（可选）

        Returns:
            删除的消息数量
        """
        query = "DELETE FROM group_messages WHERE 1=1"
        params = []

        if group_name:
            query += " AND group_name = ?"
            params.append(group_name)

        if before_time:
            query += " AND send_time < ?"
            params.append(before_time.strftime('%Y-%m-%d %H:%M:%S'))

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            deleted_count = cursor.rowcount
            conn.commit()

        logger.info(f"已清理 {deleted_count} 条消息")
        return deleted_count


# 全局单例
_storage_instance: Optional[MessageStorage] = None


def get_message_storage(db_path: Optional[str] = None) -> MessageStorage:
    """
    获取消息存储单例

    Args:
        db_path: 数据库路径（可选）

    Returns:
        MessageStorage 实例
    """
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = MessageStorage(db_path)
    return _storage_instance
