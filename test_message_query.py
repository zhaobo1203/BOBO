#!/usr/bin/env python3
"""测试消息查询"""

import os
import sys
import sqlite3
import json
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor

# 读取密钥
with open('output/account_keys.json', 'r', encoding='utf-8') as f:
    store = json.load(f)

# 获取账号密钥
account_id = 'wxid_v8g6uleh63ms11'
db_key = None
for acc_id, acc_data in store.get('accounts', {}).items():
    if acc_id == account_id or acc_id.startswith(account_id[:15]):
        db_key = acc_data.get('db_key')
        break

if not db_key:
    print(f"未找到账号 {account_id} 的密钥")
    sys.exit(1)

print(f"密钥: {db_key[:16]}...")

# 数据库路径
session_db_path = r"E:\xwechat_files\wxid_v8g6uleh63ms11_a2f9\db_storage\session\session.db"
contact_db_path = r"E:\xwechat_files\wxid_v8g6uleh63ms11_a2f9\db_storage\contact\contact.db"

# 解密 session.db
import tempfile
temp_dir = tempfile.mkdtemp(prefix="test_msg_")
decrypted_session = os.path.join(temp_dir, "session.db")

print(f"解密 session.db...")
decryptor = WeChatDatabaseDecryptor(db_key)
if not decryptor.decrypt_database(session_db_path, decrypted_session):
    print("解密失败")
    sys.exit(1)

print(f"解密成功: {decrypted_session}")

# 连接数据库
conn = sqlite3.connect(decrypted_session)
cursor = conn.cursor()

# 检查表结构
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in cursor.fetchall()]
print(f"\n数据库表: {tables}")

# 检查 SessionTable 结构
if 'SessionTable' in tables:
    cursor.execute("PRAGMA table_info(SessionTable)")
    columns = cursor.fetchall()
    print(f"\nSessionTable 表字段:")
    for col in columns:
        print(f"  - {col[1]}: {col[2]}")

    # 查看 SessionTable 中的群聊会话
    print(f"\n查看 SessionTable 中的群聊会话...")
    cursor.execute("""
        SELECT username, last_timestamp
        FROM SessionTable
        WHERE username LIKE '%@chatroom'
        ORDER BY last_timestamp DESC
        LIMIT 10
    """)
    sessions = cursor.fetchall()
    print(f"找到 {len(sessions)} 个群聊会话")
    for sess in sessions:
        print(f"  - {sess[0]}")

# 查找消息表 - 消息存储在 Msg_ 表中
print(f"\n查找消息表...")
msg_tables = [t for t in tables if t.startswith('Msg_')]
print(f"消息表: {msg_tables}")

# 消息存储在 message/*.db 中
print("\n检查消息数据库...")
message_dir = r"E:\xwechat_files\wxid_v8guleh63ms11_a2f9\db_storage\message"
message_dbs = [
    r"E:\xwechat_files\wxid_v8g6uleh63ms11_a2f9\db_storage\message\message_0.db",
    r"E:\xwechat_files\wxid_v8g6uleh63ms11_a2f9\db_storage\message\message_1.db",
    r"E:\xwechat_files\wxid_v8g6uleh63ms11_a2f9\db_storage\message\message_2.db",
    r"E:\xwechat_files\wxid_v8g6uleh63ms11_a2f9\db_storage\message\message_3.db",
    r"E:\xwechat_files\wxid_v8g6uleh63ms11_a2f9\db_storage\message\message_4.db",
    r"E:\xwechat_files\wxid_v8g6uleh63ms11_a2f9\db_storage\message\message_5.db",
]

group_id = "59157387978@chatroom"  # AI测试群

for msg_db_path in message_dbs:
    if not os.path.exists(msg_db_path):
        continue

    print(f"\n检查 {os.path.basename(msg_db_path)}...")

    # 解密消息数据库
    decrypted_msg_db = os.path.join(temp_dir, os.path.basename(msg_db_path))
    try:
        if not decryptor.decrypt_database(msg_db_path, decrypted_msg_db):
            print(f"  解密失败")
            continue
    except Exception as e:
        print(f"  解密异常: {e}")
        continue

    # 连接解密后的数据库
    msg_conn = sqlite3.connect(decrypted_msg_db)
    msg_conn.row_factory = sqlite3.Row
    msg_cursor = msg_conn.cursor()

    # 检查表结构
    msg_cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    msg_tables = [row[0] for row in msg_cursor.fetchall()]
    print(f"  表: {msg_tables}")

    # 查找包含群消息的表
    for table in msg_tables:
        if 'MSG' in table.upper() or 'MESSAGE' in table.upper() or table.upper().startswith('MSG'):
            msg_cursor.execute(f"PRAGMA table_info({table})")
            cols = [col[1] for col in msg_cursor.fetchall()]
            print(f"  {table} 字段: {cols}")

            # 尝试查询群消息
            try:
                # 检查是否有 session_username 字段
                if 'session_username' in cols:
                    msg_cursor.execute(f"""
                        SELECT * FROM {table}
                        WHERE session_username = ?
                        ORDER BY create_time DESC
                        LIMIT 5
                    """, (group_id,))
                    rows = msg_cursor.fetchall()
                    if rows:
                        print(f"  找到 {len(rows)} 条消息!")
                        for row in rows:
                            print(f"    - {dict(row)}")
                elif 'username' in cols:
                    msg_cursor.execute(f"""
                        SELECT * FROM {table}
                        WHERE username = ?
                        ORDER BY create_time DESC
                        LIMIT 5
                    """, (group_id,))
                    rows = msg_cursor.fetchall()
                    if rows:
                        print(f"  找到 {len(rows)} 条消息!")
                        for row in rows:
                            print(f"    - {dict(row)}")
            except Exception as e:
                print(f"  查询失败: {e}")

    msg_conn.close()

conn.close()

# 清理
import shutil
shutil.rmtree(temp_dir, ignore_errors=True)
