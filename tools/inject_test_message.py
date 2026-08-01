# -*- coding: utf-8 -*-
"""
行为测试：向 messages.db 注入模拟微信消息
模拟真实用户在AI测试群中发送包含股票代码的消息
"""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "messages.db"

def inject_test_messages():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    c.execute('''
        INSERT INTO group_messages 
        (sender_nickname, message_content, send_time, group_name, group_id, sender_id, message_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        '行为测试用户A',
        '今天601318中国平安走势怎么样？有没有人分析一下',
        now,
        'AI测试群',
        '12345678900@chatroom',
        'wxid_testuser001',
        1
    ))
    
    c.execute('''
        INSERT INTO group_messages 
        (sender_nickname, message_content, send_time, group_name, group_id, sender_id, message_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        '行为测试用户B',
        '000001平安银行也可以关注一下，最近走势不错',
        now,
        'AI测试群',
        '12345678900@chatroom',
        'wxid_testuser002',
        1
    ))
    
    c.execute('''
        INSERT INTO group_messages 
        (sender_nickname, message_content, send_time, group_name, group_id, sender_id, message_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        '行为测试用户C',
        '600519贵州茅台还是稳啊，白酒龙头',
        now,
        'AI测试群',
        '12345678900@chatroom',
        'wxid_testuser003',
        1
    ))
    
    conn.commit()
    
    c.execute('SELECT COUNT(*) FROM group_messages')
    total = c.fetchone()[0]
    print(f"[OK] 注入完成，总消息数: {total}")
    
    c.execute('''
        SELECT id, sender_nickname, message_content, send_time 
        FROM group_messages 
        ORDER BY id DESC LIMIT 5
    ''')
    print("\n最新5条消息:")
    for row in c.fetchall():
        print(f"  [{row[0]}] {row[1]}: {row[2][:50]} ({row[3]})")
    
    conn.close()
    return True

if __name__ == "__main__":
    inject_test_messages()