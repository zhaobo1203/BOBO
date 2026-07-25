# -*- coding: utf-8 -*-
"""检查民德电子msg_id=2795为什么漏匹配"""
import sqlite3
import sys
import os

os.system('chcp 65001 >nul 2>&1')
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 1. 查看msg_id=2795的完整内容
conn2 = sqlite3.connect('data/messages.db')
c2 = conn2.cursor()
c2.execute("SELECT id, sender_nickname, message_content, send_time, group_name FROM group_messages WHERE id=2795")
row = c2.fetchone()
if row:
    print(f'=== msg_id=2795 详情 ===')
    print(f'  sender: {row[1]}')
    print(f'  time: {row[3]}')
    print(f'  group: {row[4]}')
    print(f'  content: {row[2]}')
else:
    print('msg_id=2795 不存在!')
conn2.close()

# 2. 用matcher测试这条消息
print('\n=== 用Matcher测试匹配 ===')
sys.path.insert(0, '.')
from src.stock_analysis.services.stock_loader import StockLoader
from src.stock_analysis.services.matcher import Matcher

loader = StockLoader()
name_index = loader.get_name_index()
code_index = loader.get_code_index()
matcher = Matcher(name_index, code_index)

content = row[2] if row else ''
sender = row[1] if row else ''
send_time = row[3] if row else ''
group_name = row[4] if row else ''
matches = matcher.match_message(2795, content, sender, send_time, group_name)
print(f'匹配结果: {len(matches)}条')
for m in matches:
    print(f'  {m.stock_name}({m.stock_code}) type={m.match_type}')

# 3. 检查"民德"是否在索引中
print('\n=== 检查"民德"在索引中的情况 ===')

# 搜索包含"民德"的股票
for name, stocks in name_index.items():
    if '民德' in name:
        print(f'  name_index["{name}"] = {stocks}')

# 4. 检查消息内容中"民德电子"出现的位置
if content:
    idx = content.find('民德电子')
    if idx >= 0:
        print(f'\n  "民德电子"出现在位置 {idx}')
        start = max(0, idx - 20)
        end = min(len(content), idx + 30)
        print(f'  上下文: ...{content[start:end]}...')
    else:
        print(f'\n  "民德电子"未在内容中找到')
    
    idx2 = content.find('民德')
    if idx2 >= 0:
        print(f'  "民德"出现在位置 {idx2}')