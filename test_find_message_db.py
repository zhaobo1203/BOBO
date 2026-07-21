#!/usr/bin/env python3
"""查找消息数据库"""

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

if not db_storage:
    print("未找到 db_storage")
    sys.exit(1)

print(f"db_storage: {db_storage}")

# 列出所有数据库文件
print("\n数据库文件列表:")
for db_file in db_storage.rglob("*.db"):
    print(f"  {db_file.relative_to(db_storage)}")

# 查找 MSG 数据库
msg_db = None
for p in db_storage.glob("MSG/*.db"):
    if p.name.startswith("MSG"):
        msg_db = p
        break

if not msg_db:
    # 尝试其他路径
    for p in db_storage.glob("MSG0*.db"):
        msg_db = p
        break

if msg_db:
    print(f"\n找到消息数据库: {msg_db}")

    # 解密并查看结构
    temp_db = Path("temp_msg.db")
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
        if 'MSG' in table[0].upper() or 'MESSAGE' in table[0].upper():
            print(f"\n=== {table[0]} ===")
            cursor.execute(f"PRAGMA table_info({table[0]})")
            columns = cursor.fetchall()
            for col in columns:
                print(f"  {col[1]}: {col[2]}")

    conn.close()
    temp_db.unlink()
else:
    print("\n未找到 MSG 数据库，查看 MicroMsg.db")

    micro_msg = db_storage / "MicroMsg.db"
    if micro_msg.exists():
        print(f"MicroMsg.db 存在: {micro_msg}")
        temp_db = Path("temp_micro.db")
        decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
        decryptor.decrypt_database(str(micro_msg), str(temp_db))

        conn = sqlite3.connect(str(temp_db))
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print(f"\n表列表: {[t[0] for t in tables]}")

        for table in tables:
            print(f"\n=== {table[0]} ===")
            cursor.execute(f"PRAGMA table_info({table[0]})")
            columns = cursor.fetchall()
            for col in columns[:10]:  # 只显示前10列
                print(f"  {col[1]}: {col[2]}")

        conn.close()
        temp_db.unlink()
