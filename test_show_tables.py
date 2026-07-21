#!/usr/bin/env python3
"""查看 session.db 表结构"""

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
session_db = None
for p in data_dir.glob(f"{account_id}_*/db_storage/session/session.db"):
    session_db = p
    break

if not session_db:
    print("未找到 session.db")
    sys.exit(1)

print(f"session.db: {session_db}")

# 解密
temp_db = Path("temp_show_tables.db")
decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
decryptor.decrypt_database(str(session_db), str(temp_db))

# 查看表结构
conn = sqlite3.connect(str(temp_db))
cursor = conn.cursor()

# 获取所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print(f"\n表列表: {[t[0] for t in tables]}")

# 查看每个表的结构
for table in tables:
    table_name = table[0]
    print(f"\n=== {table_name} ===")
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()
    for col in columns:
        print(f"  {col[1]}: {col[2]}")
    
    # 显示一行数据
    try:
        cursor.execute(f"SELECT * FROM {table_name} LIMIT 1")
        row = cursor.fetchone()
        if row:
            print(f"  示例数据: {row[:5]}...")
    except:
        pass

conn.close()
temp_db.unlink()