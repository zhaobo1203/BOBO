#!/usr/bin/env python3
"""检查解密后的数据库中有哪些群聊"""
import sqlite3
import tempfile
from pathlib import Path
import time

# 查找最新的临时解密目录
temp_base = Path(tempfile.gettempdir())
temp_dirs = list(temp_base.glob('wechat_monitor_*'))

print(f'找到临时目录数: {len(temp_dirs)}')

if temp_dirs:
    latest_dir = max(temp_dirs, key=lambda x: x.stat().st_mtime)
    print(f'最新目录: {latest_dir}')

    session_db = latest_dir / 'session.db'
    contact_db = latest_dir / 'contact.db'

    print(f'session.db 存在: {session_db.exists()}')
    print(f'contact.db 存在: {contact_db.exists()}')

    # 检查 session.db
    if session_db.exists():
        print('\n=== 检查 session.db ===')
        try:
            conn = sqlite3.connect(str(session_db))
            cursor = conn.cursor()

            # 列出所有表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cursor.fetchall()]
            print(f'表: {tables}')

            # 检查 SessionTable
            if 'SessionTable' in tables:
                # 统计总数
                cursor.execute("SELECT COUNT(*) FROM SessionTable")
                total = cursor.fetchone()[0]
                print(f'SessionTable 总记录数: {total}')

                # 统计群聊数量
                cursor.execute("SELECT COUNT(*) FROM SessionTable WHERE username LIKE '%@chatroom'")
                chatroom_count = cursor.fetchone()[0]
                print(f'群聊数量: {chatroom_count}')

                # 列出前10个群聊
                if chatroom_count > 0:
                    print('\n前10个群聊:')
                    cursor.execute('''
                        SELECT username, summary
                        FROM SessionTable
                        WHERE username LIKE '%@chatroom'
                        ORDER BY sort_timestamp DESC
                        LIMIT 10
                    ''')
                    for i, row in enumerate(cursor.fetchall(), 1):
                        username, summary = row
                        print(f'  {i}. {username}')
                        if summary:
                            print(f'     摘要: {str(summary)[:50]}')

            conn.close()
        except Exception as e:
            print(f'错误: {e}')

    # 检查 contact.db
    if contact_db.exists():
        print('\n=== 检查 contact.db ===')
        try:
            conn = sqlite3.connect(str(contact_db))
            cursor = conn.cursor()

            # 列出所有表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cursor.fetchall()]
            print(f'表: {tables}')

            # 检查 chat_room 表
            if 'chat_room' in tables:
                cursor.execute("SELECT COUNT(*) FROM chat_room")
                count = cursor.fetchone()[0]
                print(f'chat_room 记录数: {count}')

                if count > 0:
                    print('\n前10个群:')
                    cursor.execute('SELECT username FROM chat_room LIMIT 10')
                    for i, row in enumerate(cursor.fetchall(), 1):
                        print(f'  {i}. {row[0]}')

            # 检查 contact 表
            if 'contact' in tables:
                cursor.execute("SELECT COUNT(*) FROM contact WHERE username LIKE '%@chatroom'")
                count = cursor.fetchone()[0]
                print(f'\ncontact 表群聊数: {count}')

                if count > 0:
                    print('前10个群:')
                    cursor.execute('''
                        SELECT username, remark
                        FROM contact
                        WHERE username LIKE '%@chatroom'
                        LIMIT 10
                    ''')
                    for i, row in enumerate(cursor.fetchall(), 1):
                        username, remark = row
                        print(f'  {i}. {username} (备注: {remark or "无"})')

            conn.close()
        except Exception as e:
            print(f'错误: {e}')
else:
    print('未找到临时解密目录')
