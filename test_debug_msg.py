#!/usr/bin/env python3
"""调试消息格式"""

import sys
import sqlite3
import hashlib
from pathlib import Path

sys.path.insert(0, 'src')

from wechat_decrypt_tool.key_store import load_account_keys_store
from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor

# 加载密钥
key_store = load_account_keys_store()
accounts = key_store.get('accounts', {})
db_key = None
account_id = None
for acc, info in accounts.items():
    if info.get('db_key'):
        account_id = acc
        db_key = info.get('db_key')
        break

print(f"Account: {account_id}")
print(f"Key: {db_key[:16]}...")

# 查找数据库
db_storage = None
data_dir = Path("E:/xwechat_files")
for p in data_dir.glob(f"{account_id}_*/db_storage"):
    db_storage = p
    break

print(f"DB Storage: {db_storage}")

# 解密联系人获取群ID
contact_db = db_storage / "contact" / "contact.db"
temp_contact = Path("temp_debug_contact.db")

decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
decryptor.decrypt_database(str(contact_db), str(temp_contact))

conn = sqlite3.connect(str(temp_contact))
cursor = conn.cursor()
cursor.execute("SELECT username, nick_name, remark FROM contact WHERE username LIKE '%@chatroom'")
groups = cursor.fetchall()
conn.close()
temp_contact.unlink()

# 找AI测试群
group_id = None
for username, nick_name, remark in groups:
    display = remark or nick_name or ""
    if "AI测试" in display:
        group_id = username
        print(f"Found group: {display} ({username})")
        break

if not group_id:
    print("Group not found")
    sys.exit(1)

# 计算表名
table_name = "Msg_" + hashlib.md5(group_id.encode()).hexdigest()
print(f"Table name: {table_name}")

# 查找消息数据库
for i in range(10):
    msg_db = db_storage / "message" / f"message_{i}.db"
    if not msg_db.exists():
        continue
    
    temp_msg = Path(f"temp_debug_msg_{i}.db")
    try:
        decryptor.decrypt_database(str(msg_db), str(temp_msg))
        
        conn = sqlite3.connect(str(temp_msg))
        cursor = conn.cursor()
        
        # 检查表是否存在
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        if cursor.fetchone():
            print(f"Found in message_{i}.db")
            
            # 查看消息表结构
            cursor.execute(f"PRAGMA table_info({table_name})")
            print("\nTable columns:")
            for col in cursor.fetchall():
                print(f"  {col[1]} ({col[2]})")
            
            # 查看最近消息的发送者信息
            cursor.execute(f"SELECT local_id, real_sender_id, message_content FROM {table_name} WHERE local_type = 1 ORDER BY local_id DESC LIMIT 10")
            print("\nRecent messages with sender:")
            for row in cursor.fetchall():
                content = row[2]
                if isinstance(content, bytes):
                    content = content.decode('utf-8', errors='replace')
                sender_id = row[1]
                print(f"ID {row[0]}: sender_id={sender_id}, content={repr(content[:50])}")
            
            conn.close()
            temp_msg.unlink()
            break
        
        conn.close()
        temp_msg.unlink()
    except Exception as e:
        print(f"Error: {e}")
        if temp_msg.exists():
            temp_msg.unlink()