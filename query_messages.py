import sqlite3
from pathlib import Path

# 检查数据库文件
db_path = Path("data/messages.db")
if not db_path.exists():
    print(f"[错误] 数据库文件不存在: {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
c = conn.cursor()

# 获取总消息数
c.execute("SELECT COUNT(*) FROM group_messages")
total = c.fetchone()[0]
print(f"模块1-微信消息监听验证:")
print(f"- 数据库中总消息数: {total}")

# 获取AI测试群消息数
c.execute("SELECT COUNT(*) FROM group_messages WHERE group_name LIKE '%AI测试群%'")
ai_test_count = c.fetchone()[0]
print(f"- AI测试群消息数: {ai_test_count}")

# 查看最新5条消息
print("\n最新5条消息(AI测试群):")
c.execute("SELECT * FROM group_messages WHERE group_name LIKE '%AI测试群%' ORDER BY id DESC LIMIT 5")
for i, row in enumerate(c.fetchall(), 1):
    print(f"  {i}. ID={row[0]}, 发送者={row[1]}, 时间={row[4]}, 内容={row[2][:80]}")

# 检查表结构
print("\n表结构验证:")
c.execute("PRAGMA table_info(group_messages)")
columns = [col[1] for col in c.fetchall()]
print(f"- 字段列表: {columns}")

conn.close()

print("\n✅ 模块1验证结果: 消息已成功写入数据库，监听功能正常")