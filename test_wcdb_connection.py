#!/usr/bin/env python3
"""测试 WCDB 连接"""
import sys
sys.path.insert(0, 'src')

print("Step 1: Importing modules...")
from pathlib import Path

print("Step 2: Setting up variables...")
db_key = '5b3ac394175641cdb67facb44badd4500854e91c5b354b5292cddc10cba4930d'
account_name = 'wxid_v8g6uleh63ms11'

print("Step 3: Finding session.db...")
session_db = None
for base in [Path(r'E:\xwechat_files'), Path(r'E:\微信临时XIN')]:
    print(f"  Checking base: {base}, exists: {base.exists()}")
    if base.exists():
        for sub in base.iterdir():
            if sub.is_dir() and account_name.lower() in sub.name.lower():
                test = sub / 'db_storage' / 'session' / 'session.db'
                print(f"    Checking: {test}, exists: {test.exists()}")
                if test.exists():
                    session_db = test
                    print(f'Found session.db: {session_db}')
                    break
        if session_db:
            break

if not session_db:
    print('session.db not found!')
    sys.exit(1)

print("Step 4: Importing WCDB modules...")
from wechat_decrypt_tool.wcdb_realtime import open_account, close_account, get_sessions

print("Step 5: Testing WCDB connection (timeout=10s)...")
try:
    handle = open_account(str(session_db), db_key, timeout=10.0)
    print(f'WCDB connected: handle={handle}')
    
    print("Step 6: Getting sessions...")
    sessions = get_sessions(handle)
    print(f'Sessions count: {len(sessions)}')
    
    groups = [s for s in sessions if '@chatroom' in s.get('username', '')]
    print(f'Groups count: {len(groups)}')
    
    close_account(handle)
    print('WCDB connection closed')
except Exception as e:
    import traceback
    print(f'Error: {type(e).__name__}: {e}')
    traceback.print_exc()