"""AI测试群监控脚本

专门用于监控"AI测试群"的消息

使用方法：
    python monitor_ai_test_group.py
    python monitor_ai_test_group.py --realtime  # 实时监控模式
"""

import os
import sys
import time
import argparse
import logging
from datetime import datetime

# 修复 Windows 控制台 Unicode 编码问题
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 设置 wechat_decrypt_tool 的日志级别为 WARNING（只记录警告和错误）
logging.getLogger('wechat_decrypt_tool').setLevel(logging.WARNING)

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入主程序函数
from wechat_main import (
    get_current_account,
    has_key,
    get_all_groups,
    get_sender_name,
    format_message,
)


def find_group_by_name(groups: dict, target_name: str) -> str:
    """根据群名查找群ID

    Args:
        groups: 群ID到群名称的映射
        target_name: 目标群名称

    Returns:
        str: 群ID，未找到返回 None
    """
    for group_id, group_name in groups.items():
        if target_name in group_name:
            return group_id
    return None


def get_group_messages_direct(db_key: str, account_dir: str, group_id: str, limit: int = 100) -> list:
    """直接从数据库获取群消息

    Args:
        db_key: 数据库密钥
        account_dir: 账号数据目录
        group_id: 群ID
        limit: 消息数量限制

    Returns:
        list: 消息列表
    """
    from wechat_core.db_decryptor import get_decrypted_connection, close_decrypted_connection

    session_db = os.path.join(account_dir, 'db_storage', 'session', 'session.db')

    if not os.path.exists(session_db):
        return []

    conn = get_decrypted_connection(db_key, session_db)
    if not conn:
        return []

    try:
        cursor = conn.cursor()

        # 首先检查表结构
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"  [调试] 表: {tables}")

        # 检查 session 表的字段
        if 'session' in tables or 'Session' in tables:
            table_name = 'session' if 'session' in tables else 'Session'
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            col_names = [col[1] for col in columns]
            print(f"  [调试] {table_name} 表字段: {col_names}")

        # 查询群消息 - 使用参数化查询和表名验证
        # 验证表名只包含合法字符（防止 SQL 注入）
        if not table_name.replace('_', '').isalnum():
            print(f"  [调试] 无效的表名: {table_name}")
            return []

        try:
            # 使用引号包裹表名，并确保表名已验证
            quoted_table = f'"{table_name}"'
            cursor.execute(f"""
                SELECT * FROM {quoted_table}
                WHERE session_username = ?
                ORDER BY create_time DESC
                LIMIT ?
            """, (group_id, limit))
        except Exception as e:
            print(f"  [调试] 查询失败: {e}")
            # 尝试不带 session_username 的查询
            try:
                cursor.execute(f"""
                    SELECT * FROM {quoted_table}
                    ORDER BY create_time DESC
                    LIMIT 5
                """)
                rows = cursor.fetchall()
                print(f"  [调试] 示例数据: {rows[:2] if rows else '无数据'}")
            except Exception as e2:
                print(f"  [调试] 查询全部也失败: {e2}")
            return []

        messages = []
        for row in cursor.fetchall():
            # 根据实际字段名提取数据
            msg = dict(row)
            messages.append(msg)

        print(f"  [调试] 找到 {len(messages)} 条消息")
        return messages
    except Exception as e:
        print(f"  [调试] 异常: {e}")
        return []
    finally:
        close_decrypted_connection(conn)


def monitor_ai_test_group(realtime: bool = False, interval: int = 5):
    """监控AI测试群

    Args:
        realtime: 是否启用实时监控模式
        interval: 轮询间隔（秒）
    """
    print("=" * 60)
    print("AI测试群监控脚本")
    print("=" * 60)
    print(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. 获取当前账号
    current = get_current_account()
    if not current:
        print("错误: 未检测到当前登录账号，请确保微信已登录")
        return

    account_id = current['account_id']
    print(f"当前账号: {account_id}")

    # 2. 检查密钥
    if not has_key(account_id):
        print("错误: 未找到账号密钥")
        return

    print("密钥状态: 已配置")

    # 3. 获取账号数据目录
    from wechat_core import get_account_info
    account_info = get_account_info(account_id)
    if not account_info:
        print("错误: 未找到账号数据目录")
        return

    account_dir = account_info['data_path']
    print(f"数据目录: {account_dir}")

    # 4. 获取密钥
    from wechat_core import get_account_key
    db_key = get_account_key(account_id)
    if not db_key:
        print("错误: 无法获取密钥")
        return

    # 5. 获取所有群聊
    print("\n正在获取群聊列表...")
    groups = get_all_groups(account_id)
    print(f"找到 {len(groups)} 个群聊")

    # 6. 查找"AI测试群"
    target_group_name = "AI测试群"
    group_id = find_group_by_name(groups, target_group_name)

    if not group_id:
        print(f"\n错误: 未找到群聊 '{target_group_name}'")
        print("\n显示部分群聊列表供参考:")
        for i, (gid, gname) in enumerate(list(groups.items())[:20]):
            print(f"  {i+1}. {gname}")
        return

    group_name = groups[group_id]
    print(f"\n找到目标群聊:")
    print(f"  群名称: {group_name}")
    print(f"  群ID: {group_id}")

    # 7. 获取历史消息
    print("\n" + "-" * 60)
    print("查询消息...")
    print("-" * 60)

    messages = get_group_messages_direct(db_key, account_dir, group_id, 20)

    if not messages:
        print("暂无消息或查询失败")
    else:
        print(f"\n找到 {len(messages)} 条消息:")
        for msg in messages[:10]:
            print(f"  {msg}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='AI测试群监控脚本')
    parser.add_argument('--realtime', action='store_true', help='启用实时监控模式')
    parser.add_argument('--interval', type=int, default=5, help='轮询间隔（秒），默认5秒')

    args = parser.parse_args()

    monitor_ai_test_group(realtime=args.realtime, interval=args.interval)


if __name__ == '__main__':
    main()
