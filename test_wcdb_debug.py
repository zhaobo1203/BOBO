#!/usr/bin/env python3
"""
WCDB 调试脚本 - 诊断 WCDB 连接问题
"""

import sys
import time
from pathlib import Path

# 添加 src 目录到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from wechat_decrypt_tool.key_store import load_account_keys_store
from wechat_decrypt_tool.wcdb_realtime import (
    open_account as wcdb_open_account,
    get_sessions as wcdb_get_sessions,
    get_messages as wcdb_get_messages,
    close_account as wcdb_close_account,
    get_native_logs,
)


def main():
    print("=" * 60)
    print("WCDB 调试脚本")
    print("=" * 60)

    # 1. 加载密钥
    print("\n[1] 加载密钥...")
    key_store = load_account_keys_store()
    if not key_store:
        print("[错误] 未找到密钥存储")
        return

    accounts = key_store.get('accounts', {})
    print(f"  可用账号: {list(accounts.keys())}")

    # 选择第一个有密钥的账号
    account_id = None
    db_key = None
    for acc, info in accounts.items():
        if info.get('db_key'):
            account_id = acc
            db_key = info.get('db_key')
            break

    if not db_key:
        print("[错误] 没有找到有效的密钥")
        return

    print(f"  使用账号: {account_id}")
    print(f"  密钥: {db_key[:16]}...")

    # 2. 查找 session.db
    print("\n[2] 查找 session.db...")
    data_dir = Path("E:/xwechat_files")
    session_db = None

    # 根据账号ID查找匹配的目录
    for p in data_dir.glob(f"{account_id}_*/db_storage/session/session.db"):
        session_db = p
        break

    if not session_db:
        # 如果没有找到匹配的，列出所有可用的
        print(f"  [警告] 未找到账号 {account_id} 的 session.db")
        print("  可用的 session.db:")
        for p in list(data_dir.glob("*_*/db_storage/session/session.db"))[:5]:
            print(f"    - {p.parent.parent.parent.name}")
        return

    print(f"  session.db: {session_db}")

    # 3. 测试 WCDB 连接
    print("\n[3] 测试 WCDB 连接...")
    print("  正在初始化 WCDB (可能需要几秒)...")

    start_time = time.time()
    try:
        handle = wcdb_open_account(str(session_db), db_key)
        elapsed = time.time() - start_time
        print(f"  [OK] WCDB 连接成功, handle={handle}, 耗时={elapsed:.2f}s")
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"  [错误] WCDB 连接失败 (耗时={elapsed:.2f}s): {e}")
        return

    # 4. 获取会话列表
    print("\n[4] 获取会话列表...")
    try:
        sessions = wcdb_get_sessions(handle)
        print(f"  [OK] 获取到 {len(sessions)} 个会话")

        # 显示前 5 个群聊
        groups = [s for s in sessions if s.get('username', '').endswith('@chatroom')]
        print(f"  群聊数量: {len(groups)}")

        for i, g in enumerate(groups[:5]):
            print(f"    {i+1}. {g.get('display_name', g.get('username', '未知'))}")

    except Exception as e:
        print(f"  [错误] 获取会话失败: {e}")

    # 5. 获取某个群的消息
    if groups:
        print("\n[5] 获取群消息...")
        group_id = groups[0].get('username')
        group_name = groups[0].get('display_name', group_id)
        print(f"  测试群: {group_name}")

        try:
            messages = wcdb_get_messages(handle, group_id, limit=5)
            print(f"  [OK] 获取到 {len(messages)} 条消息")

            for msg in messages:
                content = msg.get('message_content', '')
                if isinstance(content, bytes):
                    content = content.decode('utf-8', errors='replace')
                sender = msg.get('sender_username', '未知')
                print(f"    - {sender}: {content[:50]}...")

        except Exception as e:
            print(f"  [错误] 获取消息失败: {e}")

    # 6. 关闭连接
    print("\n[6] 关闭 WCDB 连接...")
    try:
        wcdb_close_account(handle)
        print("  [OK] 连接已关闭")
    except Exception as e:
        print(f"  [错误] 关闭连接失败: {e}")

    # 7. 获取原生日志
    print("\n[7] WCDB 原生日志...")
    try:
        logs = get_native_logs()
        if logs:
            print(f"  日志条数: {len(logs)}")
            for log in logs[-5:]:
                print(f"    {log}")
        else:
            print("  无日志")
    except Exception as e:
        print(f"  [错误] 获取日志失败: {e}")

    print("\n" + "=" * 60)
    print("调试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
