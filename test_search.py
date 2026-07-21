#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试群聊搜索功能"""
import sys
import sqlite3
from pathlib import Path
import tempfile

sys.stdout.reconfigure(encoding='utf-8')

temp_base = Path(tempfile.gettempdir())
temp_dirs = list(temp_base.glob('wechat_monitor_*'))
latest_dir = max(temp_dirs, key=lambda x: x.stat().st_mtime)
contact_db = latest_dir / 'contact.db'

print(f'contact_db: {contact_db}')
print()

# 测试搜索功能
def search_groups(keyword: str):
    """搜索群聊"""
    conn = sqlite3.connect(str(contact_db))
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT username, nick_name, remark
        FROM contact
        WHERE username LIKE '%@chatroom'
        AND (
            username LIKE ? 
            OR nick_name LIKE ? 
            OR remark LIKE ?
        )
        ORDER BY nick_name
        LIMIT 10
    """, (f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'))
    
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        username, nick_name, remark = row
        display_name = remark or nick_name or username
        results.append({
            'username': username,
            'displayName': f"{display_name} ({username})" if display_name != username else username
        })
    return results

# 测试搜索
for keyword in ['AI', '测试', 'AI测试群']:
    print(f'Search "{keyword}":')
    results = search_groups(keyword)
    for r in results:
        print(f'  - {r["displayName"]}')
    print()