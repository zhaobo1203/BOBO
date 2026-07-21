#!/usr/bin/env python3
"""
诊断脚本：检查消息数据库结构
用于排查 simple_monitor.py 无法获取历史消息的问题
"""

import os
import sys
import json
import hashlib
import tempfile
import sqlite3
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from wechat_decrypt_tool.wechat_detection import (
    detect_current_logged_in_account,
    auto_detect_wechat_data_dirs
)
from wechat_decrypt_tool.key_store import load_account_keys_store


def main():
    print("=" * 60)
    print("消息数据库诊断脚本")
    print("=" * 60)
    print()

    # 1. 检测账号和数据目录
    print("[步骤1] 检测账号和数据目录...")
    detected_dirs = auto_detect_wechat_data_dirs()
    print(f"  检测到的数据目录: {detected_dirs}")

    result = detect_current_logged_in_account()
    account_id = result.get('current_account')
    data_path = result.get('data_path')

    if not data_path and detected_dirs:
        data_path = detected_dirs[0]

    print(f"  当前账号: {account_id}")
    print(f"  数据路径: {data_path}")
    print()

    if not data_path:
        print("[错误] 未找到微信数据目录")
        return

    # 2. 加载密钥
    print("[步骤2] 加载密钥...")
    key_store = load_account_keys_store()
    db_key = None

    if key_store and 'accounts' in key_store:
        for acc_id, acc_data in key_store.get('accounts', {}).items():
            if acc_id == account_id:
                db_key = acc_data.get('db_key')
                break

    if not db_key:
        # 尝试从 output/account_keys.json 加载
        key_paths = [
            Path(__file__).parent / 'output' / 'account_keys.json',
            Path(__file__).parent / 'key_store.json',
        ]
        for key_path in key_paths:
            if key_path.exists():
                try:
                    data = json.loads(key_path.read_text(encoding='utf-8'))
                    if data and 'accounts' in data:
                        for acc_id, acc_data in data.get('accounts', {}).items():
                            if acc_id == account_id:
                                db_key = acc_data.get('db_key')
                                break
                except Exception:
                    pass

    if db_key:
        print(f"  密钥已加载: {db_key[:8]}...{db_key[-8:]} (长度={len(db_key)})")
    else:
        print("  [警告] 未找到密钥，将无法解密数据库")
    print()

    # 3. 检查目录结构
    print("[步骤3] 检查目录结构...")

    # 初始化变量
    message_path = None
    message_db_files = []
    biz_message_files = []

    db_storage_path = Path(data_path) / 'db_storage'
    print(f"  db_storage 路径: {db_storage_path}")
    print(f"  db_storage 存在: {db_storage_path.exists()}")

    # 如果 db_storage 不存在，检查其他可能的路径
    if not db_storage_path.exists():
        print(f"\n  [警告] db_storage 不存在，检查其他可能路径...")

        # 检查账号目录
        account_dir = Path(data_path) / account_id
        print(f"  账号目录: {account_dir}")
        print(f"  账号目录存在: {account_dir.exists()}")

        if account_dir.exists():
            account_db_storage = account_dir / 'db_storage'
            print(f"  账号 db_storage: {account_db_storage}")
            print(f"  账号 db_storage 存在: {account_db_storage.exists()}")

            if account_db_storage.exists():
                db_storage_path = account_db_storage

        # 检查其他检测到的数据目录
        for detected_dir in detected_dirs:
            if detected_dir == data_path:
                continue

            detected_path = Path(detected_dir)

            # 检查多种可能的路径组合
            possible_paths = [
                detected_path / 'db_storage',
                detected_path / account_id / 'db_storage',
                detected_path / 'WeChat Files' / account_id / 'db_storage',
            ]

            print(f"\n  检查目录 {detected_dir}:")
            for alt_path in possible_paths:
                exists = alt_path.exists()
                print(f"    {alt_path}: {exists}")
                if exists:
                    print(f"  [找到] 替代 db_storage: {alt_path}")
                    db_storage_path = alt_path
                    break

            if db_storage_path.exists():
                break

    if db_storage_path.exists():
        # 列出所有子目录
        subdirs = [d for d in db_storage_path.iterdir() if d.is_dir()]
        print(f"  子目录: {[d.name for d in subdirs]}")

        # 列出所有 .db 文件
        db_files = list(db_storage_path.glob('*.db'))
        print(f"  根目录 DB 文件: {[f.name for f in db_files]}")

        # 检查 message 目录
        message_path = db_storage_path / 'message'
        print(f"\n  message 路径: {message_path}")
        print(f"  message 存在: {message_path.exists()}")

        if message_path.exists():
            # 列出 message 目录下的所有 .db 文件
            message_db_files = [f for f in message_path.iterdir() if f.suffix == '.db' and not f.name.endswith('-shm') and not f.name.endswith('-wal')]
            print(f"  message 目录下的 DB 文件数量: {len(message_db_files)}")

            if message_db_files:
                # 显示前10个文件名
                print(f"  前10个文件: {[f.name for f in message_db_files[:10]]}")

                # 检查文件名模式
                biz_message_files = [f for f in message_db_files if f.name.startswith('biz_message_')]
                msg_files = [f for f in message_db_files if f.name.startswith('MSG')]
                other_files = [f for f in message_db_files if not f.name.startswith('biz_message_') and not f.name.startswith('MSG')]

                print(f"\n  文件名模式统计:")
                print(f"    biz_message_*.db: {len(biz_message_files)} 个")
                print(f"    MSG*.db: {len(msg_files)} 个")
                print(f"    其他: {len(other_files)} 个")
                if other_files:
                    print(f"    其他文件名示例: {[f.name for f in other_files[:5]]}")
    print()

    # 4. 测试解密一个消息数据库
    if db_key and message_path and message_path.exists() and message_db_files:
        print("[步骤4] 测试解密消息数据库...")

        # 选择一个数据库文件进行测试
        test_db = biz_message_files[0] if biz_message_files else message_db_files[0]
        print(f"  测试文件: {test_db.name}")

        temp_dir = tempfile.mkdtemp(prefix="wechat_debug_")
        temp_db = os.path.join(temp_dir, "test.db")

        try:
            from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor
            decryptor = WeChatDatabaseDecryptor(db_key)

            if decryptor.decrypt_database(str(test_db), temp_db):
                print(f"  解密成功!")

                # 检查表结构
                conn = sqlite3.connect(temp_db)
                cursor = conn.cursor()

                # 获取所有表名
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                print(f"  表数量: {len(tables)}")
                print(f"  表名列表: {tables[:20]}")

                # 检查 Name2Id 表
                if 'Name2Id' in tables:
                    cursor.execute("SELECT COUNT(*) FROM Name2Id")
                    count = cursor.fetchone()[0]
                    print(f"\n  Name2Id 表记录数: {count}")

                    if count > 0:
                        cursor.execute("SELECT * FROM Name2Id LIMIT 10")
                        sample_rows = cursor.fetchall()
                        print(f"  Name2Id 示例数据:")
                        for row in sample_rows[:5]:
                            print(f"    {row}")

                # 检查 Msg_ 表
                msg_tables = [t for t in tables if t.startswith('Msg_')]
                print(f"\n  Msg_ 表数量: {len(msg_tables)}")
                if msg_tables:
                    print(f"  Msg_ 表名示例: {msg_tables[:5]}")

                    # 检查第一个 Msg 表的结构
                    test_table = msg_tables[0]
                    cursor.execute(f"PRAGMA table_info({test_table})")
                    columns = cursor.fetchall()
                    print(f"\n  {test_table} 表字段:")
                    for col in columns[:10]:
                        print(f"    {col[1]} ({col[2]})")

                    # 检查是否有数据
                    cursor.execute(f"SELECT COUNT(*) FROM {test_table}")
                    count = cursor.fetchone()[0]
                    print(f"  {test_table} 记录数: {count}")

                    if count > 0:
                        # 获取一条示例数据
                        cursor.execute(f"SELECT * FROM {test_table} LIMIT 1")
                        sample = cursor.fetchone()
                        print(f"  示例数据: {sample[:5] if sample else 'None'}...")

                conn.close()
            else:
                print(f"  解密失败!")
        except Exception as e:
            print(f"  错误: {e}")
            import traceback
            traceback.print_exc()

        finally:
            # 清理临时文件
            try:
                os.remove(temp_db)
            except:
                pass
    print()

    # 5. 测试群聊ID匹配
    print("[步骤5] 测试群聊ID匹配...")
    test_group_id = "59157387978@chatroom"  # AI测试群
    group_id_hash = hashlib.md5(test_group_id.encode()).hexdigest()
    print(f"  测试群ID: {test_group_id}")
    print(f"  MD5 哈希: {group_id_hash}")

    if db_key and message_path and message_path.exists() and message_db_files:
        print(f"\n  在数据库中搜索群ID匹配...")

        for db_file in message_db_files[:3]:  # 只检查前3个
            temp_db = os.path.join(temp_dir, f"search_{db_file.name}")

            try:
                decryptor = WeChatDatabaseDecryptor(db_key)
                if not decryptor.decrypt_database(str(db_file), temp_db):
                    continue

                conn = sqlite3.connect(temp_db)
                cursor = conn.cursor()

                # 检查 Name2Id 表
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Name2Id'")
                if cursor.fetchone():
                    cursor.execute("SELECT * FROM Name2Id")
                    for row in cursor.fetchall():
                        name_val = str(row[0]) if row else ''
                        id_val = str(row[1]) if len(row) > 1 else ''
                        if group_id_hash in name_val or test_group_id in name_val:
                            print(f"  [匹配] {db_file.name}: {name_val} -> {id_val}")
                        elif test_group_id[:10] in name_val:
                            print(f"  [部分匹配] {db_file.name}: {name_val} -> {id_val}")

                # 检查 Msg 表中的 source 字段
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")
                msg_tables = [row[0] for row in cursor.fetchall()]

                for table_name in msg_tables[:3]:
                    try:
                        cursor.execute(f"PRAGMA table_info({table_name})")
                        columns = [col[1] for col in cursor.fetchall()]

                        if 'source' in columns:
                            cursor.execute(f"SELECT source FROM {table_name} WHERE source LIKE ? LIMIT 1", (f'%{test_group_id}%',))
                            match = cursor.fetchone()
                            if match:
                                print(f"  [source匹配] {db_file.name}/{table_name}")
                    except:
                        pass

                conn.close()
            except Exception as e:
                pass

            try:
                os.remove(temp_db)
            except:
                pass

    print()
    print("=" * 60)
    print("诊断完成")
    print("=" * 60)


if __name__ == '__main__':
    main()
