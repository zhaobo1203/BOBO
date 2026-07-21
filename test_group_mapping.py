#!/usr/bin/env python3
"""查找群聊对应的消息表"""

import sys
import sqlite3
import hashlib
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

# 查找数据库
data_dir = Path("E:/xwechat_files")
db_storage = None
for p in data_dir.glob(f"{account_id}_*/db_storage"):
    db_storage = p
    break

# 解密 contact.db
contact_db = db_storage / "contact" / "contact.db"
print(f"解密: {contact_db}")

temp_db = Path("temp_contact.db")
decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
decryptor.decrypt_database(str(contact_db), str(temp_db))

conn = sqlite3.connect(str(temp_db))
cursor = conn.cursor()

# 获取表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print(f"\n表列表: {[t[0] for t in tables]}")

# 查看 contact 表结构
print(f"\n=== contact ===")
cursor.execute("PRAGMA table_info(contact)")
columns = cursor.fetchall()
for col in columns:
    print(f"  {col[1]}: {col[2]}")

# 查找群聊
cursor.execute("""
    SELECT username, alias, nick_name, remark 
    FROM contact 
    WHERE username LIKE '%@chatroom'
    LIMIT 10
""")
groups = cursor.fetchall()
print(f"\n找到 {len(groups)} 个群聊:")
for g in groups:
    print(f"  {g}")

conn.close()
temp_db.unlink()

# 计算表名哈希
print("\n\n=== 群聊消息表名映射 ===")
print("WCDB 使用 MD5(群ID) 作为消息表名后缀")
print("例如: Msg_<MD5(group_id)>")

def get_msg_table_name(username: str) -> str:
    """计算消息表名"""
    md5 = hashlib.md5(username.encode()).hexdigest()
    return f"Msg_{md5}"

# 测试几个群ID
test_groups = [
    "58302701020@chatroom",  # 从之前输出看到的
    "12345678@chatroom",
]

for g in test_groups:
    table_name = get_msg_table_name(g)
    print(f"  群: {g}")
    print(f"  表: {table_name}")