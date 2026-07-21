#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查contact表中的群聊信息"""
import sqlite3
from pathlib import Path
import tempfile
import sys

# 设置输出编码
sys.stdout.reconfigure(encoding='utf-8')

temp_base = Path(tempfile.gettempdir())
temp_dirs = list(temp_base.glob('wechat_monitor_*'))
latest_dir = max(temp_dirs, key=lambda x: x.stat().st_mtime)
contact_db = latest_dir / 'contact.db'

print(f'contact_db: {contact_db}')

conn = sqlite3.connect(str(contact_db))
cursor = conn.cursor()

# 查看 contact 表结构
cursor.execute('PRAGMA table_info(contact)')
columns = cursor.fetchall()
print('\ncontact table columns:')
for col in columns:
    print(f'  {col[1]} ({col[2]})')

# 查看群聊记录
print('\nGroup examples (first 10):')
cursor.execute('''
    SELECT username, nick_name, remark, alias
    FROM contact
    WHERE username LIKE '%@chatroom'
    LIMIT 10
''')
for row in cursor.fetchall():
    print(f'  username: {row[0]}')
    print(f'  nick_name: {row[1]}')
    print(f'  remark: {row[2]}')
    print(f'  alias: {row[3]}')
    print()

# 搜索包含"AI"或"测试"的群
print('Search for "AI" or "test":')
cursor.execute('''
    SELECT username, nick_name, remark, alias
    FROM contact
    WHERE username LIKE '%@chatroom'
    AND (nick_name LIKE '%AI%' OR nick_name LIKE '%测试%' OR remark LIKE '%AI%' OR remark LIKE '%测试%')
    LIMIT 10
''')
rows = cursor.fetchall()
if rows:
    for row in rows:
        print(f'  username: {row[0]}')
        print(f'  nick_name: {row[1]}')
        print(f'  remark: {row[2]}')
        print()
else:
    print('  No matches found')

conn.close()
