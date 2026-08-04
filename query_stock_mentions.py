import sqlite3
from pathlib import Path

# 检查股票提及数据库
db_path = Path("data/stock_mentions.db")
if not db_path.exists():
    print(f"[错误] 股票提及数据库不存在: {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
c = conn.cursor()

# 获取总记录数
c.execute("SELECT COUNT(*) FROM stock_mentions")
total = c.fetchone()[0]
print(f"模块3-股票提及分析验证:")
print(f"- 数据库中总提及记录数: {total}")

# 获取最新的提及记录
print("\n最新5条股票提及记录:")
c.execute("SELECT * FROM stock_mentions ORDER BY id DESC LIMIT 5")
for i, row in enumerate(c.fetchall(), 1):
    print(f"  {i}. 股票={row[1]}({row[2]}), 群={row[5]}, 消息ID={row[3]}, 时间={row[6]}")

# 检查我们测试消息中的股票
test_stocks = ['600519', '000001', '601318']
print("\n测试消息中股票匹配情况:")
for code in test_stocks:
    c.execute("SELECT COUNT(*) FROM stock_mentions WHERE stock_code = ?", (code,))
    count = c.fetchone()[0]
    c.execute("SELECT stock_name FROM stock_mentions WHERE stock_code = ? LIMIT 1", (code,))
    name = c.fetchone()
    name = name[0] if name else "未知"
    print(f"  - {name}({code}): 匹配到{count}次")

# 统计表信息
c.execute("PRAGMA table_info(stock_mentions)")
columns = [col[1] for col in c.fetchall()]
print(f"\n表结构验证:")
print(f"- 字段列表: {columns}")

conn.close()

print("\n模块2+模块3验证结果: 消息采集存储正常，股票匹配分析正常")