#!/usr/bin/env python3
"""
监听 AI测试群 消息
"""

import sys
import time
import sqlite3
import hashlib
import logging
import re
import os
import uuid
from pathlib import Path
from datetime import datetime

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from wechat_decrypt_tool.key_store import load_account_keys_store
from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor

# 日志统一输出到 logs 文件夹
log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "monitor.log"

# 配置日志：只输出到文件，不显示在控制台
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8', mode='a')
    ]
)

# 抑制所有第三方库的日志
for logger_name in ['wechat_decrypt_tool', 'sqlcipher', 'sqlalchemy']:
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)

# 全局变量
db_key = None
db_storage = None
account_id = None
contact_cache = {}  # 发送者ID -> 昵称缓存

# 目标群名
TARGET_GROUP_NAME = "AI测试群"


def safe_print(text: str):
    """安全打印，处理编码问题"""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode('gbk', errors='replace').decode('gbk'))


def get_msg_table_name(username: str) -> str:
    """根据群ID计算消息表名"""
    md5 = hashlib.md5(username.encode()).hexdigest()
    return f"Msg_{md5}"


def load_contact_cache():
    """加载联系人缓存，用于显示发送者昵称"""
    global contact_cache
    
    contact_db = db_storage / "contact" / "contact.db"
    # 使用唯一临时文件名避免冲突
    temp_db = Path(f"temp_contact_{uuid.uuid4().hex[:8]}.db")
    
    try:
        decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
        decryptor.decrypt_database(str(contact_db), str(temp_db))
        
        conn = sqlite3.connect(str(temp_db))
        cursor = conn.cursor()
        
        cursor.execute("SELECT username, nick_name, remark FROM contact")
        for row in cursor.fetchall():
            username, nick_name, remark = row
            display_name = remark or nick_name or username
            contact_cache[username] = display_name
        
        conn.close()
        if temp_db.exists():
            temp_db.unlink()
    except Exception as e:
        logging.error(f"加载联系人缓存失败: {e}")
        if temp_db.exists():
            try:
                temp_db.unlink()
            except:
                pass


def get_sender_display_name(content: str) -> tuple:
    """
    从群消息内容中提取发送者昵称
    返回: (昵称, 剩余消息内容)
    
    群消息格式有多种：
    1. "wxid_xxx:\n消息内容"
    2. "昵称:\n消息内容"
    3. "wxid_xxx:\r\n消息内容"
    4. "wxid_xxx: 消息内容" (无换行)
    """
    if not content:
        return "未知", content
    
    # 尝试匹配 "发送者:" 后跟内容
    # 支持 : 和 ：(中文冒号)
    match = re.match(r'^([^\r\n:：]+?)\s*[:：]\s*(.*)$', content, re.DOTALL)
    if match:
        sender = match.group(1).strip()
        remaining = match.group(2).strip()
        
        # 如果是 wxid 格式，查找缓存的昵称
        if sender.startswith('wxid_') and sender in contact_cache:
            return contact_cache[sender], remaining
        
        # 如果不是 wxid 格式，直接返回作为昵称
        if not sender.startswith('wxid_'):
            return sender, remaining
        
        # 如果是 wxid 但缓存中没有，返回原始 wxid
        return sender, remaining
    
    # 整个内容就是消息（没有发送者前缀）
    return "未知", content


def find_message_db_for_group(group_id: str) -> Path:
    """查找包含指定群消息的数据库"""
    table_name = get_msg_table_name(group_id)
    
    for i in range(10):
        msg_db = db_storage / "message" / f"message_{i}.db"
        if not msg_db.exists():
            continue
        
        temp_db = Path(f"temp_find_{uuid.uuid4().hex[:8]}.db")
        try:
            decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
            decryptor.decrypt_database(str(msg_db), str(temp_db))
            
            conn = sqlite3.connect(str(temp_db))
            cursor = conn.cursor()
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
            result = cursor.fetchone()
            conn.close()
            if temp_db.exists():
                temp_db.unlink()
            
            if result:
                return msg_db
        except Exception as e:
            logging.error(f"查找数据库失败: {e}")
            if temp_db.exists():
                try:
                    temp_db.unlink()
                except:
                    pass
    
    return None


def poll_group_messages(group_id: str, group_name: str, interval: float = 3.0, max_rounds: int = 100):
    """轮询群消息"""
    table_name = get_msg_table_name(group_id)
    
    # 加载联系人缓存
    load_contact_cache()
    safe_print(f"已加载 {len(contact_cache)} 个联系人")
    
    safe_print(f"监听群: {group_name}")
    safe_print("-" * 50)
    
    # 找到数据库
    msg_db = find_message_db_for_group(group_id)
    if not msg_db:
        safe_print(f"[错误] 未找到消息数据库")
        return
    
    last_id = 0
    round_num = 0
    
    while round_num < max_rounds:
        round_num += 1
        
        # 每次使用唯一临时文件名
        temp_db = Path(f"temp_poll_{uuid.uuid4().hex[:8]}.db")
        
        try:
            # 解密数据库
            decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
            decryptor.decrypt_database(str(msg_db), str(temp_db))
            
            conn = sqlite3.connect(str(temp_db))
            cursor = conn.cursor()
            
            # 查询新消息（只查询文本消息，Type=1）
            cursor.execute(f"""
                SELECT 
                    local_id,
                    create_time,
                    message_content,
                    local_type
                FROM {table_name}
                WHERE local_id > ? AND local_type = 1
                ORDER BY local_id ASC
                LIMIT 50
            """, (last_id,))
            
            messages = cursor.fetchall()
            
            if messages:
                for msg in messages:
                    local_id, create_time, content, msg_type = msg
                    
                    # 更新最后ID
                    if local_id > last_id:
                        last_id = local_id
                    
                    # 解析时间
                    if create_time:
                        try:
                            msg_time = datetime.fromtimestamp(create_time).strftime('%H:%M:%S')
                        except:
                            msg_time = "未知时间"
                    else:
                        msg_time = "未知时间"
                    
                    # 处理内容
                    if content:
                        if isinstance(content, bytes):
                            try:
                                content = content.decode('utf-8', errors='replace')
                            except:
                                content = "<二进制数据>"
                        content = str(content)
                        
                        # 提取发送者昵称
                        sender, msg_text = get_sender_display_name(content)
                        
                        if len(msg_text) > 200:
                            msg_text = msg_text[:200] + "..."
                    else:
                        sender = "未知"
                        msg_text = "<空>"
                    
                    # 显示: 时间 | 昵称 | 消息内容
                    safe_print(f"{msg_time} | {sender} | {msg_text}")
            
            conn.close()
            
            # 删除临时文件
            if temp_db.exists():
                try:
                    temp_db.unlink()
                except:
                    pass
            
        except Exception as e:
            logging.error(f"查询消息失败: {e}")
            if temp_db.exists():
                try:
                    temp_db.unlink()
                except:
                    pass
        
        if round_num < max_rounds:
            time.sleep(interval)


def main():
    global db_key, db_storage, account_id
    
    print("=" * 50)
    print(f"监听: {TARGET_GROUP_NAME}")
    print("=" * 50)
    
    # 1. 加载密钥
    key_store = load_account_keys_store()
    if not key_store:
        print("[错误] 未找到密钥存储")
        return
    
    accounts = key_store.get('accounts', {})
    for acc, info in accounts.items():
        if info.get('db_key'):
            account_id = acc
            db_key = info.get('db_key')
            break
    
    if not db_key:
        print("[错误] 没有找到有效的密钥")
        return
    
    # 2. 查找数据库路径
    data_dir = Path("E:/xwechat_files")
    for p in data_dir.glob(f"{account_id}_*/db_storage"):
        db_storage = p
        break
    
    if not db_storage:
        print("[错误] 未找到数据库目录")
        return
    
    # 3. 获取群聊列表并查找目标群
    contact_db = db_storage / "contact" / "contact.db"
    temp_db = Path(f"temp_contact_{uuid.uuid4().hex[:8]}.db")
    
    decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
    decryptor.decrypt_database(str(contact_db), str(temp_db))
    
    conn = sqlite3.connect(str(temp_db))
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT username, nick_name, remark 
        FROM contact 
        WHERE username LIKE '%@chatroom'
    """)
    
    groups = cursor.fetchall()
    conn.close()
    if temp_db.exists():
        temp_db.unlink()
    
    # 查找目标群
    target_group = None
    for username, nick_name, remark in groups:
        display_name = remark or nick_name or ""
        if TARGET_GROUP_NAME in display_name:
            target_group = (username, display_name)
            break
    
    if not target_group:
        print(f"[错误] 未找到群: {TARGET_GROUP_NAME}")
        return
    
    group_id = target_group[0]
    group_name = target_group[1]
    
    # 开始监听
    poll_group_messages(
        group_id=group_id,
        group_name=group_name,
        interval=3.0,
        max_rounds=100
    )
    
    print("\n监听结束")


if __name__ == "__main__":
    main()