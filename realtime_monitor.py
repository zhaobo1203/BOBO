#!/usr/bin/env python3
"""
微信群实时消息监听脚本
========================
使用直接数据库轮询方式，可靠地监听群消息

使用方法:
    python realtime_monitor.py --list              # 列出所有群聊
    python realtime_monitor.py "群名称"            # 查看历史消息
    python realtime_monitor.py "群名称" --realtime # 实时监听
"""

import os
import sys
import time
import sqlite3
import hashlib
import tempfile
import argparse
import re
import zstandard as zstd
from pathlib import Path
from datetime import datetime

# 修复 Windows 控制台编码
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except:
        pass

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from wechat_decrypt_tool.key_store import load_account_keys_store
from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor
from wechat_decrypt_tool.wechat_detection import auto_detect_wechat_data_dirs


def decode_message_content(content):
    """解码消息内容（处理 zstd 压缩）"""
    zstd_magic = b"\x28\xb5\x2f\xfd"

    if content is None:
        return ""

    # 处理 bytes 类型
    if isinstance(content, bytes):
        if content.startswith(zstd_magic):
            try:
                decompressor = zstd.ZstdDecompressor()
                decompressed = decompressor.decompress(content)
                return decompressed.decode('utf-8', errors='replace')
            except:
                pass
        return content.decode('utf-8', errors='replace')

    # 处理 hex 字符串
    text = str(content).strip()
    if len(text) >= 16 and len(text) % 2 == 0:
        try:
            raw = bytes.fromhex(text)
            if raw.startswith(zstd_magic):
                decompressor = zstd.ZstdDecompressor()
                decompressed = decompressor.decompress(raw)
                return decompressed.decode('utf-8', errors='replace')
        except:
            pass

    return text


def format_time(timestamp):
    """格式化时间戳"""
    if not timestamp:
        return "未知时间"
    try:
        ts = int(timestamp)
        dt = datetime.fromtimestamp(ts)
        now = datetime.now()

        if dt.date() == now.date():
            return dt.strftime("%H:%M:%S")
        elif (now.date() - dt.date()).days == 1:
            return f"昨天 {dt.strftime('%H:%M:%S')}"
        elif dt.year == now.year:
            return dt.strftime("%m-%d %H:%M:%S")
        else:
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return "未知时间"


def is_text_message(content, local_type):
    """判断是否为文本消息"""
    if local_type == 10000:  # 系统消息
        return False
    if local_type in (3, 34, 43, 47, 48, 50):  # 图片、语音、视频、表情、位置、通话
        return False
    if local_type == 49:  # 链接、文件等
        return False
    if not content or len(content.strip()) < 1:
        return False
    if content.strip().startswith('<?xml') or content.strip().startswith('<msg>'):
        return False
    return True


def get_msg_table_name(username):
    """根据群ID计算消息表名"""
    md5 = hashlib.md5(username.encode()).hexdigest()
    return f"Msg_{md5}"


def find_message_db(db_storage, table_name, db_key):
    """查找包含指定表的消息数据库"""
    for i in range(10):
        msg_db = db_storage / "message" / f"message_{i}.db"
        if not msg_db.exists():
            continue

        temp_check = tempfile.mktemp(suffix='.db')
        try:
            decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
            if decryptor.decrypt_database(str(msg_db), temp_check):
                conn = sqlite3.connect(temp_check)
                cursor = conn.cursor()
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
                result = cursor.fetchone()
                conn.close()

                if result:
                    return msg_db
        except:
            pass
        finally:
            try:
                os.remove(temp_check)
            except:
                pass

    return None


def get_group_list(db_storage, db_key):
    """获取群聊列表"""
    contact_db = db_storage / "contact" / "contact.db"
    if not contact_db.exists():
        return []

    temp_db = tempfile.mktemp(suffix='.db')
    try:
        decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
        if not decryptor.decrypt_database(str(contact_db), temp_db):
            return []

        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT username, nick_name, remark
            FROM contact
            WHERE username LIKE '%@chatroom'
            ORDER BY id DESC
        """)

        groups = []
        for row in cursor.fetchall():
            username, nick_name, remark = row
            display_name = remark or nick_name or username
            groups.append({
                'username': username,
                'display_name': display_name
            })

        conn.close()
        return groups

    except Exception as e:
        print(f"[错误] 获取群列表失败: {e}")
        return []
    finally:
        try:
            os.remove(temp_db)
        except:
            pass


def main():
    parser = argparse.ArgumentParser(description="微信群实时消息监听")
    parser.add_argument('group_name', nargs='?', help='群名称')
    parser.add_argument('--list', action='store_true', help='列出所有群聊')
    parser.add_argument('--realtime', action='store_true', help='实时监听模式')
    parser.add_argument('--limit', type=int, default=20, help='消息数量')
    args = parser.parse_args()

    print("=" * 60)
    print("微信群实时消息监听")
    print("=" * 60)

    # 1. 加载密钥
    print("\n[1] 加载密钥...")
    key_store = load_account_keys_store()
    if not key_store:
        print("[错误] 未找到密钥存储，请先运行密钥获取脚本")
        return

    accounts = key_store.get('accounts', {})
    account_id = None
    db_key = None
    data_path = None

    for acc, info in accounts.items():
        if info.get('db_key'):
            account_id = acc
            db_key = info.get('db_key')
            data_path = info.get('data_path')
            break

    if not db_key:
        print("[错误] 没有找到有效的密钥")
        return

    print(f"  账号: {account_id}")
    print(f"  密钥: {db_key[:16]}...")

    # 2. 查找数据库路径
    print("\n[2] 查找数据库路径...")
    db_storage = None

    if data_path:
        potential = Path(data_path)
        if 'db_storage' in str(data_path):
            db_storage = potential
        else:
            db_storage = potential / "db_storage"

    if not db_storage or not db_storage.exists():
        data_dirs = auto_detect_wechat_data_dirs()
        for data_dir in data_dirs:
            import glob
            matches = glob.glob(str(Path(data_dir) / f"{account_id}_*" / "db_storage"))
            if matches:
                db_storage = Path(matches[0])
                break

    if not db_storage or not db_storage.exists():
        print("[错误] 未找到数据库目录")
        return

    print(f"  数据库目录: {db_storage}")

    # 3. 获取群列表
    print("\n[3] 加载群列表...")
    groups = get_group_list(db_storage, db_key)
    print(f"  找到 {len(groups)} 个群聊")

    # 列出群聊模式
    if args.list or not args.group_name:
        print("\n" + "=" * 60)
        print("群聊列表:")
        print("=" * 60)

        for i, g in enumerate(groups[:50], 1):
            try:
                safe_name = g['display_name'].encode('gbk', errors='replace').decode('gbk')
                print(f"  {i:3d}. {safe_name}")
            except:
                print(f"  {i:3d}. [编码错误]")

        if len(groups) > 50:
            print(f"\n  ... 还有 {len(groups) - 50} 个群")

        print(f"\n共 {len(groups)} 个群聊")
        print("\n使用方法:")
        print('  python realtime_monitor.py "群名称"            # 查看历史消息')
        print('  python realtime_monitor.py "群名称" --realtime # 实时监听')
        return

    # 4. 查找指定群
    print(f"\n[4] 查找群: {args.group_name}")
    group_id = None
    group_name = None

    for g in groups:
        if args.group_name == g['username'] or args.group_name == g['display_name'] or args.group_name in g['display_name']:
            group_id = g['username']
            group_name = g['display_name']
            break

    if not group_id:
        print(f"[错误] 未找到群: {args.group_name}")
        return

    print(f"  群名称: {group_name}")
    print(f"  群ID: {group_id}")

    # 5. 查找消息数据库
    table_name = get_msg_table_name(group_id)
    print(f"  消息表: {table_name}")

    print("\n[5] 查找消息数据库...")
    msg_db = find_message_db(db_storage, table_name, db_key)

    if not msg_db:
        print(f"[错误] 未找到包含群消息的数据库")
        return

    print(f"  数据库: {msg_db.name}")

    # 6. 实时监听或显示历史
    if args.realtime:
        # 实时监听模式
        print("\n" + "=" * 60)
        print(f"[实时监听] {group_name}")
        print("=" * 60)
        print("按 Ctrl+C 停止监听")
        print("-" * 60)

        # 获取当前最新消息ID
        last_local_id = 0
        temp_db = tempfile.mktemp(suffix='.db')

        try:
            decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
            if decryptor.decrypt_database(str(msg_db), temp_db):
                conn = sqlite3.connect(temp_db)
                cursor = conn.cursor()
                cursor.execute(f"SELECT MAX(local_id) FROM {table_name}")
                result = cursor.fetchone()
                last_local_id = result[0] if result and result[0] else 0
                conn.close()
        except Exception as e:
            print(f"[错误] 初始化失败: {e}")
            return
        finally:
            try:
                os.remove(temp_db)
            except:
                pass

        print(f"开始监听，当前最新消息ID: {last_local_id}")

        # 开始轮询
        poll_interval = 2
        try:
            while True:
                time.sleep(poll_interval)

                temp_db = tempfile.mktemp(suffix='.db')
                try:
                    decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
                    if not decryptor.decrypt_database(str(msg_db), temp_db):
                        continue

                    conn = sqlite3.connect(temp_db)
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()

                    # 查询新消息
                    cursor.execute(f"""
                        SELECT
                            local_id,
                            create_time,
                            message_content,
                            local_type,
                            sender_username
                        FROM {table_name}
                        WHERE local_id > ?
                        ORDER BY local_id ASC
                        LIMIT 20
                    """, (last_local_id,))

                    messages = cursor.fetchall()

                    for msg in messages:
                        local_id = msg['local_id']
                        create_time = msg['create_time']
                        content = msg['message_content'] or ''
                        local_type = msg['local_type'] or 0
                        sender_username = msg['sender_username'] or ''

                        # 更新最新ID
                        if local_id > last_local_id:
                            last_local_id = local_id

                        # 解码消息内容
                        content = decode_message_content(content)

                        # 过滤非文本消息
                        if not is_text_message(content, local_type):
                            continue

                        # 尝试从内容中提取发送者
                        sender_display = sender_username
                        if ':\n' in content[:50]:
                            match = re.match(r'^([^:]+):\n(.*)$', content, re.DOTALL)
                            if match:
                                sender_display = match.group(1)
                                content = match.group(2)

                        # 格式化时间
                        time_str = format_time(create_time)

                        # 显示消息
                        print(f"\n[{time_str}] {sender_display}")
                        print(f"  {content}")

                    conn.close()

                except Exception as e:
                    pass
                finally:
                    try:
                        os.remove(temp_db)
                    except:
                        pass

        except KeyboardInterrupt:
            print("\n" + "-" * 60)
            print("[监听已停止]")

    else:
        # 显示历史消息
        print("\n" + "=" * 60)
        print(f"历史消息 - {group_name}")
        print("=" * 60)

        temp_db = tempfile.mktemp(suffix='.db')
        try:
            decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
            if decryptor.decrypt_database(str(msg_db), temp_db):
                conn = sqlite3.connect(temp_db)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute(f"""
                    SELECT
                        local_id,
                        create_time,
                        message_content,
                        local_type,
                        sender_username
                    FROM {table_name}
                    ORDER BY create_time DESC
                    LIMIT ?
                """, (args.limit,))

                messages = cursor.fetchall()

                if not messages:
                    print("\n  暂无消息")
                else:
                    # 反转顺序，按时间正序显示
                    messages = list(reversed(messages))

                    print()
                    for msg in messages:
                        create_time = msg['create_time']
                        content = msg['message_content'] or ''
                        local_type = msg['local_type'] or 0
                        sender_username = msg['sender_username'] or ''

                        # 解码消息内容
                        content = decode_message_content(content)

                        # 过滤非文本消息
                        if not is_text_message(content, local_type):
                            continue

                        # 尝试从内容中提取发送者
                        sender_display = sender_username
                        if ':\n' in content[:50]:
                            match = re.match(r'^([^:]+):\n(.*)$', content, re.DOTALL)
                            if match:
                                sender_display = match.group(1)
                                content = match.group(2)

                        # 格式化时间
                        time_str = format_time(create_time)

                        print(f"[{time_str}] {sender_display}")
                        print(f"  {content}")
                        print()

                conn.close()

        except Exception as e:
            print(f"[错误] 获取消息失败: {e}")

        finally:
            try:
                os.remove(temp_db)
            except:
                pass


if __name__ == "__main__":
    main()
