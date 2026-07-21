#!/usr/bin/env python3
"""详细解析 ext_buffer 格式"""

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

# 获取 ext_buffer
group_id = "59157387978@chatroom"
cursor.execute("SELECT ext_buffer FROM chat_room WHERE username = ?", (group_id,))
row = cursor.fetchone()
if row and row[0]:
    data = row[0]
    print("=== 原始 hex 数据 ===")
    print(data.hex())
    print("\n=== 逐字节解析 ===")
    
    # 手动解析
    i = 0
    while i < len(data):
        print(f"\n位置 {i}: 0x{data[i]:02x}")
        if data[i] == 0x0a:
            i += 1
            length = data[i]
            print(f"  字段类型: 0x0a (成员), 长度={length}")
            i += 1
            
            # 打印整个 block
            block = data[i:i+length]
            print(f"  Block hex: {block.hex()}")
            print(f"  Block 内容: {block}")
            
            # 解析 block 内部
            j = 0
            while j < len(block):
                if block[j] == 0x0a:
                    j += 1
                    slen = block[j]
                    j += 1
                    val = block[j:j+slen]
                    print(f"    0x0a 字段: 长度={slen}, 值={val}")
                    j += slen
                elif block[j] == 0x12:
                    j += 1
                    slen = block[j]
                    j += 1
                    val = block[j:j+slen]
                    print(f"    0x12 字段: 长度={slen}, 值={val}")
                    j += slen
                elif block[j] == 0x18:
                    j += 1
                    val = block[j]
                    print(f"    0x18 字段: 值={val}")
                    j += 1
                elif block[j] == 0x22:
                    j += 1
                    slen = block[j]
                    j += 1
                    val = block[j:j+slen]
                    print(f"    0x22 字段: 长度={slen}, 值={val}")
                    j += slen
                else:
                    print(f"    未知字段 0x{block[j]:02x}")
                    j += 1
            
            i += length
        else:
            i += 1

conn.close()
temp_contact.unlink()

# 检查消息中的 real_sender_id
print("\n\n=== 消息中所有不同的 real_sender_id ===")
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
            cursor2.execute(f"SELECT DISTINCT real_sender_id FROM \"{table_name}\" ORDER BY real_sender_id")
            print(f"real_sender_id 列表: {[row[0] for row in cursor2.fetchall()]}")
        
        conn2.close()
        temp_msg.unlink()
        break
    except Exception as e:
        print(f"Error: {e}")
        if temp_msg.exists():
            temp_msg.unlink()