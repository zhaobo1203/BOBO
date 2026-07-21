#!/usr/bin/env python3
"""查看消息表结构"""

import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from wechat_decrypt_tool.key_store import load_account_keys_store
from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor

# 加载密钥
key_store = load_account_keys_store()
accounts = key_store.get('accounts', {})

account_id = None
db_key = None
for acc, info in accounts.items():
    if info.get('db_key'):
        account_id = acc
        db_key = info.get('db_key')
        break

if not db_key:
    print("未找到密钥")
    sys.exit(1)

# 查找数据库
data_dir = Path("E:/xwechat_files")
db_storage = None
for p in data_dir.glob(f"{account_id}_*/db_storage"):
    db_storage = p
    break

# 解密 message_0.db
msg_db = db_storage / "message" / "message_0.db"
print(f"解密: {msg_db}")

temp_db = Path("temp_msg0.db")
decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
decryptor.decrypt_database(str(msg_db), str(temp_db))

conn = sqlite3.connect(str(temp_db))
cursor = conn.cursor()

# 获取表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print(f"\n表列表: {[t[0] for t in tables]}")

# 查看 MSG 表结构
for table in tables:
    print(f"\n=== {table[0]} ===")
    cursor.execute(f"PRAGMA table_info({table[0]})")
    columns = cursor.fetchall()
    for col in columns:
        print(f"  {col[1]}: {col[2]}")
    
    # 显示示例数据
    try:
        cursor.execute(f"SELECT * FROM {table[0]} LIMIT 1")
        row = cursor.fetchone()
        if row:
            col_names = [c[1] for c in columns]
            print(f"  列名: {col_names[:10]}...")
            print(f"  示例: {row[:5]}...")
    except Exception as e:
        print(f"  查询失败: {e}")

conn.close()
temp_db.unlink()