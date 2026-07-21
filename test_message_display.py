#!/usr/bin/env python3
"""测试消息获取和显示"""
import sys
sys.path.insert(0, 'src')

from pathlib import Path
from wechat_decrypt_tool.wcdb_realtime import open_account, close_account, get_messages
from datetime import datetime

print("=== 测试消息获取 ===")

db_key = '5b3ac394175641cdb67facb44badd4500854e91c5b354b5292cddc10cba4930d'
session_db = Path(r'E:\xwechat_files\wxid_v8g6uleh63ms11_a2f9\db_storage\session\session.db')

print(f"连接 WCDB...")
handle = open_account(str(session_db), db_key, timeout=10.0)
print(f'WCDB handle: {handle}')

group_id = '59157387978@chatroom'
print(f"获取群 {group_id} 的消息...")
messages = get_messages(handle, group_id, limit=5)
print(f'消息数: {len(messages)}')
print()

for i, msg in enumerate(messages, 1):
    msg_time = msg.get('create_time') or 0
    try:
        msg_time_int = int(msg_time) if msg_time else 0
    except:
        msg_time_int = 0
    time_str = datetime.fromtimestamp(msg_time_int).strftime('%Y-%m-%d %H:%M:%S') if msg_time_int else '无时间'
    sender = msg.get('sender_username') or '未知'
    content = msg.get('message_content', '') or ''
    if isinstance(content, bytes):
        content = content.decode('utf-8', errors='replace')
    content_preview = content[:60] if content else '(空)'

    print(f'{i}. [{time_str}] {sender}: {content_preview}')

close_account(handle)
print()
print("=== 测试完成 ===")
