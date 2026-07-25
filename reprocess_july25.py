# -*- coding: utf-8 -*-
"""重新处理7月25日的消息匹配"""
import sys
import io
import sqlite3

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 导入匹配器组件
from src.stock_analysis.services.stock_loader import StockLoader
from src.stock_analysis.services.matcher import Matcher
from src.stock_analysis.services.storage import StorageService

# 1. 加载股票库
loader = StockLoader()
stocks = loader.load()
name_index = {s.name: s for s in stocks}
code_index = {s.code: s for s in stocks}
print(f"股票库加载完成: 名称索引{len(name_index)}条, 代码索引{len(code_index)}条")

# 2. 初始化匹配器
matcher = Matcher(name_index, code_index)

# 3. 读取7月25日的消息
msg_conn = sqlite3.connect('data/messages.db')
msg_c = msg_conn.cursor()
msg_c.execute("""
    SELECT id, sender_nickname, message_content, send_time, group_name 
    FROM group_messages 
    WHERE send_time LIKE '2026-07-25%'
    ORDER BY send_time
""")
messages = msg_c.fetchall()
msg_conn.close()
print(f"7月25日消息: {len(messages)}条")

# 4. 批量匹配
all_records = matcher.match_messages_batch(messages)
print(f"匹配结果: {len(all_records)}条提及记录")

# 5. 保存到数据库
storage = StorageService()
saved = storage.save_mentions(all_records)
print(f"保存完成: {saved}条")

# 6. 验证美利信的匹配
mention_conn = sqlite3.connect('data/stock_mentions.db')
mention_c = mention_conn.cursor()
mention_c.execute("""
    SELECT stock_name, stock_code, send_time, sender, message_content, match_type 
    FROM stock_mentions 
    WHERE stock_name = '美利信' OR stock_code = '301307'
    ORDER BY send_time
""")
rows = mention_c.fetchall()
print(f"\n=== 美利信匹配记录（修复后）: {len(rows)}条 ===")
for r in rows:
    print(f"  [{r[2]}] {r[3]} | {r[0]}({r[1]}) | {r[5]} | {r[4][:80]}")

# 7. 验证第1条消息的多股票匹配
mention_c.execute("""
    SELECT stock_name, stock_code, send_time, message_content 
    FROM stock_mentions 
    WHERE send_time = '2026-07-25 13:12:44'
    ORDER BY stock_name
""")
rows2 = mention_c.fetchall()
print(f"\n=== 13:12:44消息的多股票匹配（修复后）: {len(rows2)}条 ===")
for r in rows2:
    print(f"  {r[0]}({r[1]}) | {r[3][:80]}")

mention_conn.close()