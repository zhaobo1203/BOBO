# -*- coding: utf-8 -*-
"""交互测试验证脚本"""
import sqlite3
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 1. 检查stock_mentions.db中的匹配记录
conn = sqlite3.connect('data/stock_mentions.db')
c = conn.cursor()

c.execute("SELECT COUNT(*) FROM stock_mentions WHERE group_name='股票交流群'")
test_count = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM stock_mentions")
total_count = c.fetchone()[0]

print(f"=== stock_mentions.db ===")
print(f"测试群匹配记录: {test_count}")
print(f"总匹配记录: {total_count}")

# 按月统计
c.execute("""SELECT substr(send_time,1,7) as month, COUNT(*) 
             FROM stock_mentions WHERE group_name='股票交流群' 
             GROUP BY month ORDER BY month""")
print(f"\n按月统计:")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]}条")

# 黑名单验证 - 检查是否有误匹配
blacklist_checks = [
    ("平安夜", "平安银行"),
    ("海洋公园", "海洋"),
    ("科技部", "科技"),
    ("电子商务", "电子"),
    ("经济发展", "发展"),
    ("新能源", "能源"),
    ("平安保险", "中国平安"),
    ("龙头企业", "龙头"),
    ("信息中心", "信息"),
]
print(f"\n=== 黑名单过滤验证 ===")
for content_keyword, stock_keyword in blacklist_checks:
    c.execute("SELECT COUNT(*) FROM stock_mentions WHERE message_content LIKE ? AND group_name='股票交流群'", 
              (f'%{content_keyword}%',))
    count = c.fetchone()[0]
    status = "PASS" if count == 0 else "FAIL"
    print(f"  [{status}] 含'{content_keyword}'的消息匹配数: {count} (期望0)")

# 非股票消息验证
non_stock_checks = ["天气真好", "去爬山", "吃什么", "假期", "端午", "暑假"]
print(f"\n=== 非股票消息验证 ===")
for keyword in non_stock_checks:
    c.execute("SELECT COUNT(*) FROM stock_mentions WHERE message_content LIKE ? AND group_name='股票交流群'", 
              (f'%{keyword}%',))
    count = c.fetchone()[0]
    status = "PASS" if count == 0 else "FAIL"
    print(f"  [{status}] 含'{keyword}'的消息匹配数: {count} (期望0)")

# 正向匹配验证
stock_checks = [
    ("贵州茅台", "600519"),
    ("比亚迪", "002594"),
    ("宁德时代", "300750"),
    ("中国平安", "601318"),
    ("兆易创新", "603986"),
    ("平安银行", "000001"),
    ("浦发银行", "600000"),
    ("万科A", "000002"),
]
print(f"\n=== 正向匹配验证 ===")
for name, code in stock_checks:
    c.execute("SELECT COUNT(*) FROM stock_mentions WHERE stock_code=? AND group_name='股票交流群'", (code,))
    count = c.fetchone()[0]
    status = "PASS" if count > 0 else "FAIL"
    print(f"  [{status}] {name}({code}): {count}条匹配 (期望>0)")

# 2. 检查messages.db
conn2 = sqlite3.connect('data/messages.db')
c2 = conn2.cursor()
c2.execute("SELECT COUNT(*) FROM group_messages WHERE group_id='interaction_test'")
msg_count = c2.fetchone()[0]
print(f"\n=== messages.db ===")
print(f"interaction_test消息: {msg_count}条")

conn.close()
conn2.close()

# 3. API验证
print(f"\n=== API验证 ===")
try:
    import urllib.request, json
    # 日统计
    resp = urllib.request.urlopen('http://localhost:8000/api/stats/daily', timeout=5)
    data = json.loads(resp.read().decode('utf-8'))
    print(f"日统计: {data.get('stock_count', 0)}只股票")
    
    # 周统计
    resp = urllib.request.urlopen('http://localhost:8000/api/stats/weekly', timeout=5)
    data = json.loads(resp.read().decode('utf-8'))
    print(f"周统计: {data.get('stock_count', 0)}只股票")
    
    # 月统计 - 2月
    resp = urllib.request.urlopen('http://localhost:8000/api/stats/monthly?year=2026&month=2', timeout=5)
    data = json.loads(resp.read().decode('utf-8'))
    print(f"2月统计: {data.get('stock_count', 0)}只股票")
    
    # 月统计 - 6月
    resp = urllib.request.urlopen('http://localhost:8000/api/stats/monthly?year=2026&month=6', timeout=5)
    data = json.loads(resp.read().decode('utf-8'))
    print(f"6月统计: {data.get('stock_count', 0)}只股票")
    
    # 月统计 - 7月
    resp = urllib.request.urlopen('http://localhost:8000/api/stats/monthly?year=2026&month=7', timeout=5)
    data = json.loads(resp.read().decode('utf-8'))
    print(f"7月统计: {data.get('stock_count', 0)}只股票")
    
    print("API服务: 正常")
except Exception as e:
    print(f"API服务: 异常 - {e}")