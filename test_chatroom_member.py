#!/usr/bin/env python3
"""查找 real_sender_id 的正确映射"""

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

# 查找数据库
db_storage = None
data_dir = Path("E:/xwechat_files")
for p in data_dir.glob(f"{account_id}_*/db_storage"):
    db_storage = p
    break

decryptor = WeChatDatabaseDecryptor(key_hex=db_key)

# 解密联系人数据库
contact_db = db_storage / "contact" / "contact.db"
temp_contact = Path("temp_contact_test.db")
decryptor.decrypt_database(str(contact_db), str(temp_contact))

conn = sqlite3.connect(str(temp_contact))
cursor = conn.cursor()

group_id = "59157387978@chatroom"

# 1. 查找群的 room_id
cursor.execute("SELECT id, nick_name FROM contact WHERE username = ?", (group_id,))
row = cursor.fetchone()
room_contact_id = row[0] if row else None
print(f"群 contact.id = {room_contact_id}")

# 2. 查看 chatroom_member 中该群的所有 member_id
cursor.execute("SELECT room_id, member_id FROM chatroom_member WHERE room_id = ?", (room_contact_id,))
members = cursor.fetchall()
print(f"\nchatroom_member 中 room_id={room_contact_id} 的成员:")
for room_id, member_id in members:
    print(f"  member_id={member_id}")

# 3. 查找 member_id=2 或 member_id=3 的记录（对应消息中的 real_sender_id）
print("\n=== 查找 member_id 为小数字的记录 ===")
cursor.execute("SELECT room_id, member_id FROM chatroom_member WHERE member_id IN (2, 3, 4, 5) LIMIT 20")
for row in cursor.fetchall():
    print(f"  room_id={row[0]}, member_id={row[1]}")

# 4. 查看 encrypt_name2id 表
print("\n=== encrypt_name2id 表结构 ===")
cursor.execute("PRAGMA table_info(encrypt_name2id)")
for col in cursor.fetchall():
    print(f"  {col[1]} ({col[2]})")

# 5. 查看 chat_room 表结构
print("\n=== chat_room 表结构 ===")
cursor.execute("PRAGMA table_info(chat_room)")
for col in cursor.fetchall():
    print(f"  {col[1]} ({col[2]})")

# 6. 查看 chat_room_info_detail 表结构
print("\n=== chat_room_info_detail 表结构 ===")
cursor.execute("PRAGMA table_info(chat_room_info_detail)")
for col in cursor.fetchall():
    print(f"  {col[1]} ({col[2]})")

# 7. 查看 chat_room 表数据
print("\n=== chat_room 数据样本 ===")
cursor.execute("SELECT * FROM chat_room LIMIT 5")
cols = [desc[0] for desc in cursor.description]
print(f"列: {cols}")
for row in cursor.fetchall():
    print(f"  {row}")

conn.close()
temp_contact.unlink()

# 8. 检查消息数据库中是否有其他发送者相关字段
print("\n=== 消息表所有字段详情 ===")
table_name = "Msg_" + hashlib.md5(group_id.encode()).hexdigest()

for i in range(10):
    msg_db = db_storage / "message" / f"message_{i}.db"
    if not msg_db.exists():
        continue
    
    temp_msg = Path(f"temp_msg_test_{i}.db")
    try:
        decryptor.decrypt_database(str(msg_db), str(temp_msg))
        conn2 = sqlite3.connect(str(temp_msg))
        cursor2 = conn2.cursor()
        
        cursor2.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        if cursor2.fetchone():
            # 查看完整字段列表
            cursor2.execute(f"PRAGMA table_info(\"{table_name}\")")
            print(f"\n表 {table_name} 字段:")
            for col in cursor2.fetchall():
                print(f"  {col[1]} ({col[2]})")
            
            # 查看一条完整消息
            cursor2.execute(f"SELECT * FROM \"{table_name}\" WHERE local_type = 1 ORDER BY local_id DESC LIMIT 1")
            cols = [desc[0] for desc in cursor2.description]
            row = cursor2.fetchone()
            if row:
                print("\n完整消息示例:")
                for i, col in enumerate(cols):
                    val = row[i]
                    if isinstance(val, bytes):
                        try:
                            val = val.decode('utf-8', errors='replace')
                        except:
                            val = "<binary>"
                    print(f"  {col}: {repr(val)[:100]}")
        
        conn2.close()
        temp_msg.unlink()
        break
    except Exception as e:
        print(f"  Error: {e}")
        if temp_msg.exists():
            temp_msg.unlink()