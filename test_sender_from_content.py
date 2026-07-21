#!/usr/bin/env python3
"""从消息内容中提取发送者"""

import sys
import sqlite3
import hashlib
import re
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
print(f"当前登录微信ID: {account_id}")

# 查找数据库
db_storage = None
data_dir = Path("E:/xwechat_files")
for p in data_dir.glob(f"{account_id}_*/db_storage"):
    db_storage = p
    break

decryptor = WeChatDatabaseDecryptor(key_hex=db_key)

# 解密联系人获取昵称
contact_db = db_storage / "contact" / "contact.db"
temp_contact = Path("temp_contact.db")
decryptor.decrypt_database(str(contact_db), str(temp_contact))

conn = sqlite3.connect(str(temp_contact))
cursor = conn.cursor()

# 获取当前用户的昵称
cursor.execute("SELECT nick_name, remark FROM contact WHERE username = ?", (account_id,))
row = cursor.fetchone()
my_nickname = row[0] if row else account_id
print(f"当前用户昵称: {my_nickname}")

# 获取群成员昵称映射
group_id = "59157387978@chatroom"
cursor.execute("SELECT username, nick_name, remark FROM contact WHERE username LIKE '%@chatroom' OR username LIKE 'wxid_%'")
contact_map = {}
for row in cursor.fetchall():
    display = row[2] or row[1] or row[0]
    contact_map[row[0]] = display

conn.close()
temp_contact.unlink()

# 查看消息
table_name = "Msg_" + hashlib.md5(group_id.encode()).hexdigest()

print("\n=== 分析消息内容中的发送者信息 ===")

for i in range(10):
    msg_db = db_storage / "message" / f"message_{i}.db"
    if not msg_db.exists():
        continue
    
    temp_msg = Path(f"temp_msg_{i}.db")
    try:
        decryptor.decrypt_database(str(msg_db), str(temp_msg))
        conn = sqlite3.connect(str(temp_msg))
        cursor = conn.cursor()
        
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        if cursor.fetchone():
            cursor.execute(f"""
                SELECT local_id, real_sender_id, message_content, source 
                FROM "{table_name}" 
                WHERE local_type = 1 
                ORDER BY local_id DESC 
                LIMIT 20
            """)
            
            for row in cursor.fetchall():
                content = row[2]
                if isinstance(content, bytes):
                    content = content.decode('utf-8', errors='replace')
                
                source = row[3]
                if isinstance(source, bytes):
                    source = source.decode('utf-8', errors='replace')
                
                sender_id = row[1]
                
                # 尝试从内容中提取发送者
                # 格式: "昵称:\n内容" 或 "昵称:\n"
                sender_from_content = None
                
                # 检查是否是自己发的消息
                # 如果 real_sender_id 较小 (如2)，可能是自己
                if sender_id <= 10:
                    sender_from_content = my_nickname
                else:
                    # 尝试从内容中提取
                    if ':\n' in content[:50]:
                        match = re.match(r'^([^:]+):\n', content)
                        if match:
                            sender_from_content = match.group(1)
                
                # 显示结果
                print(f"\nmsg_id={row[0]}: sender_id={sender_id}")
                print(f"  发送者: {sender_from_content or '未知'}")
                print(f"  内容: {repr(content[:50])}")
                print(f"  source: {repr(source[:100]) if source else '空'}")
        
        conn.close()
        temp_msg.unlink()
        break
    except Exception as e:
        print(f"Error: {e}")
        if temp_msg.exists():
            temp_msg.unlink()