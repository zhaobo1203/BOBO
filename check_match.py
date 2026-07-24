# -*- coding: utf-8 -*-
"""检查匹配情况"""
import sqlite3
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 检查消息中包含股票名称的情况
conn = sqlite3.connect('data/messages.db')
cursor = conn.cursor()

# 搜索包含常见股票名称的消息
stock_names = ['平安银行', '万科', '兆易创新', '昆仑万维', '中国平安', '贵州茅台', '比亚迪', '宁德时代', '海光']

for name in stock_names:
    cursor.execute(
        "SELECT id, message_content FROM group_messages WHERE message_content LIKE ? LIMIT 3",
        (f'%{name}%',)
    )
    rows = cursor.fetchall()
    print(f'\n=== "{name}" 找到 {len(rows)} 条消息 ===')
    for r in rows:
        content = r[1][:150] if r[1] else ''
        print(f'  ID={r[0]}: {content}')

# 统计总消息数
cursor.execute("SELECT COUNT(*) FROM group_messages")
total = cursor.fetchone()[0]
print(f'\n总消息数: {total}')

# 检查匹配结果
conn2 = sqlite3.connect('data/stock_mentions.db')
cursor2 = conn2.cursor()
cursor2.execute("SELECT COUNT(*) FROM stock_mentions")
mention_count = cursor2.fetchone()[0]
print(f'匹配到的提及记录数: {mention_count}')

cursor2.execute("SELECT stock_code, stock_name, match_type, COUNT(*) as cnt FROM stock_mentions GROUP BY stock_code ORDER BY cnt DESC")
rows = cursor2.fetchall()
print(f'\n匹配到的股票:')
for r in rows:
    print(f'  {r[0]} {r[1]} ({r[2]}) - {r[3]}次')

conn.close()
conn2.close()