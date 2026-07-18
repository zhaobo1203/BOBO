"""TN-05/TN-06: 消息监听与处理模块

功能：
- 获取群聊历史消息
- 实时监听新消息
- 解析发送者昵称
- 处理消息内容（zstd解压）
"""

import os
import re
import sqlite3
import tempfile
from datetime import datetime
from typing import List, Dict, Optional

# zstd 解压（可选）
try:
    import zstandard as zstd
    ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
except ImportError:
    zstd = None
    ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def decode_message_content(message_value) -> str:
    """解码消息内容（处理zstd压缩）
    
    Args:
        message_value: 消息内容（可能是bytes或str）
        
    Returns:
        str: 解码后的消息内容
    """
    if message_value is None:
        return ""
    
    if isinstance(message_value, bytes):
        # 检查是否是 zstd 压缩
        if message_value.startswith(ZSTD_MAGIC):
            try:
                decompressor = zstd.ZstdDecompressor()
                return decompressor.decompress(message_value).decode('utf-8')
            except Exception:
                pass
        
        # 尝试直接解码
        try:
            return message_value.decode('utf-8', errors='replace')
        except Exception:
            return str(message_value)
    
    return str(message_value)


def is_text_message(content: str) -> bool:
    """判断是否为文字消息
    
    Args:
        content: 消息内容
        
    Returns:
        bool: 是否为文字消息
    """
    if not content or len(content.strip()) < 1:
        return False
    
    # XML 消息不是文字消息
    if content.strip().startswith('<?xml') or content.strip().startswith('<msg>'):
        return False
    
    # 系统消息
    if content.strip().startswith('<sysmsg'):
        return False
    
    return True


def clean_nickname(nickname: str) -> str:
    """清理昵称，移除末尾的ID部分
    
    Args:
        nickname: 原始昵称
        
    Returns:
        str: 清理后的昵称
    """
    if not nickname:
        return ""
    
    nickname = nickname.strip()
    
    # 方法1: 按 ": " 或 "：" 分割，取第一部分
    for sep in [': ', '：', ':']:
        if sep in nickname:
            parts = nickname.split(sep)
            first_part = parts[0].strip()
            if len(parts) > 1:
                second_part = parts[1].strip()
                # 移除末尾可能的冒号
                second_part_clean = second_part.rstrip(':').strip()
                # 如果第二部分是wxid格式或用户名格式，返回第一部分
                if second_part_clean.startswith('wxid_') or re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', second_part_clean):
                    return first_part
            return first_part
    
    # 方法2: 使用正则清理
    cleaned = re.sub(r'\s*[:\uff1a]\s*(wxid_[a-zA-Z0-9_]+|[a-zA-Z][a-zA-Z0-9_]*)\s*$', '', nickname)
    
    if cleaned and cleaned.strip():
        return cleaned.strip()
    
    return nickname


def get_sender_nickname_from_db(db_key: str, account_dir: str, sender_id: str) -> str:
    """从 contact.db 获取发送者昵称
    
    Args:
        db_key: 数据库密钥
        account_dir: 账号数据目录
        sender_id: 发送者ID
        
    Returns:
        str: 昵称，失败返回 "未知"
    """
    from .db_decryptor import get_decrypted_connection, close_decrypted_connection
    
    contact_db = os.path.join(account_dir, 'db_storage', 'contact', 'contact.db')
    
    if not os.path.exists(contact_db):
        return "未知"
    
    conn = get_decrypted_connection(db_key, contact_db)
    if not conn:
        return "未知"
    
    try:
        cursor = conn.cursor()
        
        # 查询联系人信息
        cursor.execute("""
            SELECT remark, nick_name, alias 
            FROM contact 
            WHERE username = ?
            LIMIT 1
        """, (sender_id,))
        
        row = cursor.fetchone()
        if row:
            # 优先使用备注名，然后是昵称，最后是别名
            nickname = row['remark'] or row['nick_name'] or row['alias'] or sender_id
            return clean_nickname(nickname)
        
        return "未知"
    except Exception:
        return "未知"
    finally:
        close_decrypted_connection(conn)


def get_group_messages_from_decrypted_db(db_key: str, account_dir: str, group_id: str, limit: int = 100) -> List[Dict]:
    """从解密后的数据库获取群消息
    
    Args:
        db_key: 数据库密钥
        account_dir: 账号数据目录
        group_id: 群ID
        limit: 最大消息数量
        
    Returns:
        list: 消息列表
    """
    from .db_decryptor import get_decrypted_connection, close_decrypted_connection
    
    session_db = os.path.join(account_dir, 'db_storage', 'session', 'session.db')
    
    if not os.path.exists(session_db):
        return []
    
    conn = get_decrypted_connection(db_key, session_db)
    if not conn:
        return []
    
    try:
        cursor = conn.cursor()
        
        # 查询群消息
        cursor.execute("""
            SELECT 
                localId,
                msgSvrId,
                create_time,
                message_content,
                sender_username,
                session_username
            FROM session 
            WHERE session_username = ?
            ORDER BY create_time DESC
            LIMIT ?
        """, (group_id, limit))
        
        messages = []
        for row in cursor.fetchall():
            content = decode_message_content(row['message_content'])
            
            messages.append({
                'local_id': row['localId'],
                'msg_svr_id': row['msgSvrId'],
                'create_time': row['create_time'],
                'content': content,
                'sender_username': row['sender_username'],
                'session_username': row['session_username'],
                'is_text': is_text_message(content)
            })
        
        return messages
    except Exception:
        return []
    finally:
        close_decrypted_connection(conn)


def get_sessions_from_decrypted_db(db_key: str, account_dir: str) -> List[Dict]:
    """从解密后的数据库获取会话列表
    
    Args:
        db_key: 数据库密钥
        account_dir: 账号数据目录
        
    Returns:
        list: 会话列表
    """
    from .db_decryptor import get_decrypted_connection, close_decrypted_connection
    
    session_db = os.path.join(account_dir, 'db_storage', 'session', 'session.db')
    
    if not os.path.exists(session_db):
        return []
    
    conn = get_decrypted_connection(db_key, session_db)
    if not conn:
        return []
    
    try:
        cursor = conn.cursor()
        
        # 查询会话列表（只获取群聊）
        cursor.execute("""
            SELECT DISTINCT
                session_username
            FROM session 
            WHERE session_username LIKE '%@chatroom'
            ORDER BY create_time DESC
        """)
        
        sessions = []
        for row in cursor.fetchall():
            sessions.append({
                'session_id': row['session_username']
            })
        
        return sessions
    except Exception:
        return []
    finally:
        close_decrypted_connection(conn)


def format_timestamp(timestamp) -> str:
    """格式化时间戳
    
    Args:
        timestamp: 时间戳（秒）
        
    Returns:
        str: 格式化后的时间字符串
    """
    if not timestamp:
        return "未知时间"
    
    try:
        ts = int(timestamp)
        dt = datetime.fromtimestamp(ts)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return "未知时间"


def get_group_names(db_key: str, account_dir: str) -> Dict[str, str]:
    """获取群名称映射
    
    Args:
        db_key: 数据库密钥
        account_dir: 账号数据目录
        
    Returns:
        dict: 群ID到群名称的映射
    """
    from .db_decryptor import get_decrypted_connection, close_decrypted_connection
    
    contact_db = os.path.join(account_dir, 'db_storage', 'contact', 'contact.db')
    
    if not os.path.exists(contact_db):
        return {}
    
    conn = get_decrypted_connection(db_key, contact_db)
    if not conn:
        return {}
    
    try:
        cursor = conn.cursor()
        
        # 查询群聊
        cursor.execute("""
            SELECT username, remark, nick_name, alias 
            FROM contact 
            WHERE username LIKE '%@chatroom'
        """)
        
        group_names = {}
        for row in cursor.fetchall():
            group_id = row['username']
            name = row['remark'] or row['nick_name'] or row['alias'] or group_id
            group_names[group_id] = name
        
        return group_names
    except Exception:
        return {}
    finally:
        close_decrypted_connection(conn)