#!/usr/bin/env python3
"""检查 packed_info_data 字段"""

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
group_id = "59157387978@chatroom"
table_name = "Msg_" + hashlib.md5(group_id.encode()).hexdigest()

for i in range(10):
    msg_db = db_storage / "message" / f"message_{i}.db"
    if not msg_db.exists():
        continue
    
    temp_msg = Path(f"temp_packed_{i}.db")
    try:
        decryptor.decrypt_database(str(msg_db), str(temp_msg))
        conn = sqlite3.connect(str(temp_msg))
        cursor = conn.cursor()
        
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        if cursor.fetchone():
            # 查看 packed_info_data 字段
            cursor.execute(f"""
                SELECT local_id, real_sender_id, message_content, packed_info_data 
                FROM "{table_name}" 
                WHERE local_type = 1 
                ORDER BY local_id DESC 
                LIMIT 5
            """)
            
            print("\n=== 消息 packed_info_data 分析 ===")
            for row in cursor.fetchall():
                content = row[2]
                if isinstance(content, bytes):
                    content = content.decode('utf-8', errors='replace')
                
                packed = row[3]
                print(f"\nmsg_id={row[0]}, sender_id={row[1]}")
                print(f"  content: {repr(content[:50])}")
                
                if packed:
                    print(f"  packed_info 长度: {len(packed)}")
                    print(f"  packed_info hex: {packed[:100].hex()}")
                    print(f"  packed_info 原始: {packed[:100]}")
                else:
                    print(f"  packed_info: 空")
        
        conn.close()
        temp_msg.unlink()
        break
    except Exception as e:
        print(f"Error: {e}")
        if temp_msg.exists():
            temp_msg.unlink()