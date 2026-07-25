# -*- coding: utf-8 -*-
"""详细检查美利信匹配 - 找出漏匹配的1条"""
import sqlite3
import sys
import os

os.system('chcp 65001 >nul 2>&1')
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 1. 查看stock_mentions中7月25日美利信的所有记录
conn = sqlite3.connect('data/stock_mentions.db')
c = conn.cursor()
c.execute("SELECT id, message_id, stock_code, stock_name, match_type, sender, send_time, group_name, message_content FROM stock_mentions WHERE stock_code='301307' AND send_time >= '2026-07-25' ORDER BY send_time")
rows = c.fetchall()
print(f'=== 模块3 美利信(301307) 7月25日匹配记录: {len(rows)}条 ===')
for i, r in enumerate(rows):
    content_preview = (r[8] or '')[:60]
    print(f'  [{i+1}] id={r[0]} msg_id={r[1]} time={r[6]} content={content_preview}')
conn.close()

# 2. 查看group_messages中7月25日AI测试群含"美利信"的不同内容消息
conn2 = sqlite3.connect('data/messages.db')
c2 = conn2.cursor()

# 按内容去重，看有多少条不同内容的美利信消息
c2.execute("""
    SELECT MIN(id), sender_nickname, message_content, send_time, group_name, COUNT(*) as cnt
    FROM group_messages 
    WHERE message_content LIKE '%美利信%' AND send_time >= '2026-07-25'
    GROUP BY message_content
    ORDER BY send_time
""")
rows2 = c2.fetchall()
print(f'\n=== 7月25日含"美利信"的不同内容消息: {len(rows2)}条 ===')
for i, r in enumerate(rows2):
    content_preview = (r[2] or '')[:80]
    print(f'  [{i+1}] msg_id={r[0]} time={r[3]} 群数={r[5]} content={content_preview}')

# 3. 用Matcher逐条测试
print(f'\n=== 用Matcher逐条测试不同内容消息 ===')
sys.path.insert(0, '.')
from src.stock_analysis.services.stock_loader import StockLoader
from src.stock_analysis.services.matcher import Matcher

loader = StockLoader()
name_index = loader.get_name_index()
code_index = loader.get_code_index()
matcher = Matcher(name_index, code_index)

matched_contents = set(r[8] for r in rows)  # 已匹配的消息内容

for i, r in enumerate(rows2):
    msg_id, sender, content, send_time, group_name, cnt = r
    matches = matcher.match_message(msg_id, content, sender, send_time, group_name)
    meilixin_matched = any(m.stock_code == '301307' for m in matches)
    in_db = content in matched_contents
    status = '✓已入库' if in_db else ('✓匹配未入库' if meilixin_matched else '✗未匹配')
    print(f'  [{i+1}] {status} msg_id={msg_id} time={send_time}')
    if not meilixin_matched:
        idx = content.find('美利信')
        if idx >= 0:
            start = max(0, idx - 15)
            end = min(len(content), idx + 20)
            print(f'       上下文: ...{content[start:end]}...')

conn2.close()