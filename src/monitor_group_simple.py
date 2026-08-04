#!/usr/bin/env python3
"""
微信群消息监听脚本 - 简洁版
=====================================
基于 TN-01 至 TN-06 技术节点实现

功能:
- TN-01: 微信进程管理
- TN-02: 当前登录账号检测
- TN-03: 密钥获取
- TN-04: SQLCipher 数据库解密
- TN-05: WCDB 实时消息监听
- TN-06: 群消息提取与存储

特点:
- 只显示文本消息，过滤图片、表情、链接等
- 显示群名称（而非群ID）
- 显示发送者昵称（而非用户名）
- 显示时间和消息内容
"""

import argparse
import glob
import logging
import os
import re
import sqlite3
import sys
import tempfile
import time
import zstandard as zstd
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 设置日志级别 - 减少 wechat_decrypt_tool 的日志输出
logging.getLogger('wechat_decrypt_tool').setLevel(logging.WARNING)

from wechat_decrypt_tool.wechat_detection import (
    get_process_list,
    auto_detect_wechat_data_dirs,
    detect_current_logged_in_account,
)
from wechat_decrypt_tool.key_store import load_account_keys_store
from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor
from wechat_decrypt_tool.wcdb_realtime import (
    open_account as wcdb_open_account,
    get_messages as wcdb_get_messages,
    close_account as wcdb_close_account,
)
from wechat_decrypt_tool.chat_helpers import _iter_message_db_paths, _resolve_msg_table_name

# 配置
POLL_INTERVAL = 2  # 轮询间隔（秒）


def _decompress_zstd(data: bytes) -> str:
    """尝试zstd解压数据，如果失败返回原始内容解码"""
    zstd_magic = b"\x28\xb5\x2f\xfd"
    if data.startswith(zstd_magic):
        try:
            decompressor = zstd.ZstdDecompressor()
            decompressed = decompressor.decompress(data)
            return decompressed.decode('utf-8', errors='replace')
        except (zstd.ZstdError, OSError, UnicodeDecodeError):
            pass
    return data.decode('utf-8', errors='replace')


def decode_message_content(message_value: Any) -> str:
    """解码消息内容（处理 zstd 压缩）"""
    if message_value is None:
        return ""

    # 处理 bytes 类型
    if isinstance(message_value, bytes):
        return _decompress_zstd(message_value)

    # 处理 hex 字符串
    text = str(message_value).strip()
    if len(text) >= 16 and len(text) % 2 == 0:
        try:
            raw = bytes.fromhex(text)
            return _decompress_zstd(raw)
        except (ValueError, zstd.ZstdError, OSError):
            pass

    return text


def is_text_message(content: str, local_type: int) -> bool:
    """判断是否为纯文本消息（过滤图片、表情、链接等）"""
    # local_type: 1=文本, 3=图片, 34=语音, 43=视频, 47=动画表情, 48=位置, 10000=系统消息
    if local_type == 10000:  # 系统消息
        return False
    if local_type in (3, 34, 43, 47, 48, 50):  # 图片、语音、视频、表情、位置、通话
        return False
    if local_type == 49:  # 链接、文件、小程序等复合消息
        return False

    # 检查内容
    if not content or len(content.strip()) < 1:
        return False

    # 过滤 XML 格式的消息（图片、表情、链接等）
    content_stripped = content.strip()
    if content_stripped.startswith('<?xml') or content_stripped.startswith('<msg>'):
        return False

    # 过滤空的或纯空白内容
    if not content_stripped:
        return False

    # 过滤微信表情包消息（格式如: [0K][oK][呲牙][微笑] 等）
    # 表情包消息通常只包含 [xxx] 格式的表情标记
    # 检查是否为纯表情消息（只有 [xxx] 格式的内容）
    # 匹配微信表情格式: [表情名] 或 [0K] 等特殊标记
    emoji_pattern = r'^(\[[\w\u4e00-\u9fa5]+\]\s*)+$'
    if re.match(emoji_pattern, content_stripped):
        return False

    return True


def format_time(timestamp: Any) -> str:
    """格式化时间戳为可读格式"""
    if timestamp is None:
        return "未知时间"
    try:
        ts = int(timestamp)
        dt = datetime.fromtimestamp(ts)
        now = datetime.now()

        # 今天：显示时间
        if dt.date() == now.date():
            return dt.strftime("%H:%M:%S")
        # 昨天
        elif (now.date() - dt.date()).days == 1:
            return f"昨天 {dt.strftime('%H:%M:%S')}"
        # 本年：显示月日时间
        elif dt.year == now.year:
            return dt.strftime("%m-%d %H:%M:%S")
        # 跨年：显示完整日期
        else:
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OSError):
        return "未知时间"


def decrypt_contact_db(contact_db_path: Path, db_key: str) -> Dict[str, Dict]:
    """解密 contact.db 获取联系人/群名称映射"""
    # 使用 NamedTemporaryFile 替代不安全的 mktemp
    temp_file = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    temp_db = temp_file.name
    temp_file.close()  # 关闭文件句柄，让 sqlite3 可以访问
    try:
        decryptor = WeChatDatabaseDecryptor(db_key)
        if not decryptor.decrypt_database(str(contact_db_path), temp_db):
            return {}

        conn = sqlite3.connect(temp_db)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 查询所有联系人（包括群聊）
        # 注意: ext_buffer 列可能不存在，使用动态查询
        cursor.execute("PRAGMA table_info(contact)")
        columns = [row[1] for row in cursor.fetchall()]

        # 构建查询字段
        select_fields = ['username', 'remark', 'nick_name', 'alias']
        if 'ext_buffer' in columns:
            select_fields.append('ext_buffer')

        cursor.execute(f"SELECT {', '.join(select_fields)} FROM contact")

        contacts = {}
        for row in cursor.fetchall():
            username = row['username']
            # 优先使用备注，其次昵称，再次别名
            display_name = row['remark'] or row['nick_name'] or row['alias'] or username
            contacts[username] = {
                'display_name': display_name,
                'nick_name': row['nick_name'],
                'remark': row['remark'],
                'alias': row['alias'],
            }

        conn.close()
        return contacts
    except Exception as e:
        print(f"[错误] 解密 contact.db 失败: {e}")
        return {}
    finally:
        try:
            os.remove(temp_db)
        except OSError:
            pass


def get_group_display_name(group_id: str, contacts: Dict[str, Dict]) -> str:
    """获取群的显示名称"""
    if group_id in contacts:
        return contacts[group_id].get('display_name', group_id)
    return group_id


def get_sender_display_name(sender_username: str, contacts: Dict[str, Dict]) -> str:
    """获取发送者的显示名称（昵称）"""
    if sender_username in contacts:
        return contacts[sender_username].get('display_name', sender_username)
    return sender_username


def extract_sender_from_content(content: str, current_user_nickname: str, contacts: Dict[str, Dict]) -> tuple:
    """从消息内容中提取发送者昵称

    返回: (发送者昵称, 清理后的内容)
    """
    # 检查消息内容是否以 "昵称:\n" 格式开头
    if ':\n' in content[:50]:
        match = re.match(r'^([^:]+):\n(.*)$', content, re.DOTALL)
        if match:
            sender_name = match.group(1)
            clean_content = match.group(2)

            # 验证发送者名称是否在联系人中
            for username, info in contacts.items():
                display = info.get('display_name', '')
                if display == sender_name:
                    return sender_name, clean_content

            # 如果不在联系人中，仍然返回提取的名称
            return sender_name, clean_content

    return None, content


def get_sender_by_real_sender_id(real_sender_id: int, current_account: str, current_user_nickname: str) -> str:
    """根据 real_sender_id 判断发送者

    规律发现：
    - real_sender_id 较小值（如2）通常是当前登录用户自己
    """
    if real_sender_id <= 10:
        return current_user_nickname
    return None


def get_group_messages_from_db(
    account_dir: Path,
    db_key: str,
    group_id: str,
    contacts: Dict[str, Dict],
    limit: int = 20
) -> List[Dict]:
    """从解密后的消息数据库获取群消息"""
    messages = []

    # 遍历所有消息数据库
    db_paths = _iter_message_db_paths(account_dir)
    if not db_paths:
        return messages

    # 使用 NamedTemporaryFile 替代不安全的 mktemp
    temp_file = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    temp_db = temp_file.name
    temp_file.close()
    try:
        decryptor = WeChatDatabaseDecryptor(db_key)

        for db_path in db_paths:
            try:
                # 解密数据库
                if not decryptor.decrypt_database(str(db_path), temp_db):
                    continue

                # 使用 with 确保连接总是被关闭，防止资源泄漏
                with sqlite3.connect(temp_db) as conn:
                    conn.row_factory = sqlite3.Row

                    # 查找群对应的消息表
                    table_name = _resolve_msg_table_name(conn, group_id)
                    if not table_name:
                        # 尝试其他表名格式
                        cursor = conn.cursor()
                        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                        for row in cursor.fetchall():
                            table = row[0]
                            if 'msg' in table.lower() or 'chat' in table.lower():
                                # 检查表中是否有该群的消息
                                try:
                                    test_sql = f'SELECT COUNT(*) FROM "{table}" WHERE talker = ? LIMIT 1'
                                    count = conn.execute(test_sql, (group_id,)).fetchone()
                                    if count and count[0] > 0:
                                        table_name = table
                                        break
                                except sqlite3.Error:
                                    continue

                    if not table_name:
                        continue

                    # 查询消息 - 必须查询该分片所有消息，不限制
                    quoted_table = f'"{table_name}"'
                    sql = f'''
                        SELECT
                            local_id,
                            create_time,
                            talker,
                            sender_username,
                            message_content,
                            local_type,
                            status
                        FROM {quoted_table}
                        WHERE talker = ?
                        ORDER BY create_time DESC
                    '''

                    cursor = conn.cursor()
                    cursor.execute(sql, (group_id,))

                    for row in cursor.fetchall():
                        local_type = int(row['local_type'] or 0)
                        content = decode_message_content(row['message_content'])

                        # 只保留文本消息
                        if not is_text_message(content, local_type):
                            continue

                        sender_username = row['sender_username'] or ''
                        sender_display = get_sender_display_name(sender_username, contacts)

                        messages.append({
                            'create_time': row['create_time'],
                            'sender_username': sender_username,
                            'sender_display': sender_display,
                            'content': content,
                            'local_type': local_type,
                        })

            except sqlite3.Error as e:
                print(f"[警告] 处理数据库 {db_path.name} 时出错: {e}")
                continue

    finally:
        try:
            os.remove(temp_db)
        except OSError:
            pass

    # 按时间正序排列，最新消息在最后
    messages.sort(key=lambda x: int(x.get('create_time') or 0))
    # 截取最新的 limit 条消息
    if len(messages) > limit:
        return messages[-limit:]
    return messages


def get_group_messages_via_wcdb(
    handle: int,
    group_id: str,
    contacts: Dict[str, Dict],
    limit: int = 20,
    current_account: str = None,
    current_user_nickname: str = None
) -> List[Dict]:
    """通过 WCDB 获取群消息

    参数:
        handle: WCDB 句柄
        group_id: 群ID
        contacts: 联系人映射
        limit: 返回消息数量限制
        current_account: 当前登录账号ID
        current_user_nickname: 当前登录用户昵称
    """
    messages = []

    try:
        raw_messages = wcdb_get_messages(handle, group_id, limit=limit * 2)  # 多取一些，因为会过滤

        for msg in raw_messages:
            local_type = int(msg.get('local_type') or 0)
            content = decode_message_content(msg.get('message_content'))

            # 只保留文本消息
            if not is_text_message(content, local_type):
                continue

            # 获取 real_sender_id
            real_sender_id = int(msg.get('real_sender_id') or 0)

            # 尝试多种方式确定发送者
            sender_display = None
            clean_content = content

            # 方法1: 从消息内容中提取 "昵称:\n" 格式
            extracted_sender, clean_content = extract_sender_from_content(
                content, current_user_nickname, contacts
            )
            if extracted_sender:
                sender_display = extracted_sender

            # 方法2: 通过 real_sender_id 判断
            if not sender_display and real_sender_id and current_user_nickname:
                sender_display = get_sender_by_real_sender_id(
                    real_sender_id, current_account, current_user_nickname
                )

            # 方法3: 使用旧的 sender_username 方式
            if not sender_display:
                sender_username = msg.get('sender_username') or ''
                sender_display = get_sender_display_name(sender_username, contacts)

            # 最终回退
            if not sender_display:
                sender_display = '未知'

            messages.append({
                'create_time': msg.get('create_time'),
                'sender_display': sender_display,
                'content': clean_content,
                'local_type': local_type,
                'real_sender_id': real_sender_id,
            })

        # 按时间正序排列
        messages.sort(key=lambda x: int(x.get('create_time') or 0))
        return messages[:limit]

    except Exception as e:
        print(f"[错误] WCDB 获取消息失败: {e}")
        return messages


def monitor_group_realtime(
    account_dir: Path,
    db_key: str,
    group_id: str,
    group_name: str,
    contacts: Dict[str, Dict],
    poll_interval: int = 2,
    current_account: str = None,
    current_user_nickname: str = None
):
    """实时监听群消息"""
    print("\n" + "=" * 60)
    print(f"[实时监听] {group_name}")
    print("=" * 60)

    # 连接 WCDB
    session_db_path = account_dir / "session" / "session.db"

    try:
        handle = wcdb_open_account(str(session_db_path), db_key)
        if handle <= 0:
            print("[错误] WCDB 连接失败")
            return
    except Exception as e:
        print(f"[错误] WCDB 连接异常: {e}")
        return

    # 获取初始最新消息时间
    messages = get_group_messages_via_wcdb(
        handle, group_id, contacts, 10,
        current_account, current_user_nickname
    )
    last_create_time = max(
        int(msg.get('create_time') or 0) for msg in messages
    ) if messages else 0

    print(f"  开始时间: {format_time(last_create_time)}")
    print(f"  轮询间隔: {poll_interval} 秒")
    print("  按 Ctrl+C 停止监听")
    print("-" * 60)

    try:
        while True:
            time.sleep(poll_interval)

            # 获取最新消息
            new_messages = get_group_messages_via_wcdb(handle, group_id, contacts, limit=10)

            # 检查新消息
            for msg in new_messages:
                msg_time = int(msg.get('create_time') or 0)
                if msg_time > last_create_time:
                    last_create_time = msg_time

                    # 显示新消息
                    time_str = format_time(msg_time)
                    sender = msg.get('sender_display', '未知')
                    content = msg.get('content', '')

                    print(f"\n[{time_str}] {sender}")
                    print(f"  {content}")

    except KeyboardInterrupt:
        print("\n" + "-" * 60)
        print("[监听已停止]")
    finally:
        wcdb_close_account(handle)


def list_available_groups(account_dir: Path, db_key: str) -> Dict[str, str]:
    """列出可用的群聊"""
    # 解密 contact.db 获取群名称
    contact_db_path = account_dir / "contact" / "contact.db"
    if not contact_db_path.exists():
        print(f"[错误] contact.db 不存在: {contact_db_path}")
        return {}

    contacts = decrypt_contact_db(contact_db_path, db_key)

    # 筛选群聊
    groups = {}
    for username, info in contacts.items():
        if username.endswith('@chatroom'):
            display_name = info.get('display_name', username)
            groups[username] = display_name

    return groups


def main():
    parser = argparse.ArgumentParser(description="微信群消息监听 - 简洁版")
    parser.add_argument("--group", "-g", help="指定群名称或群ID进行监听")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有可用群聊")
    parser.add_argument("--realtime", "-r", action="store_true", help="实时监听模式")
    parser.add_argument("--interval", "-i", type=int, default=2, help="轮询间隔（秒）")
    parser.add_argument("--limit", "-n", type=int, default=20, help="显示消息数量")
    args = parser.parse_args()

    print("=" * 60)
    print("微信群消息监听系统 - 简洁版")
    print("技术节点: TN-01 ~ TN-06")
    print("=" * 60)

    # ========== TN-01: 微信进程管理 ==========
    print("\n[TN-01] 检测微信进程...")
    process_list = get_process_list()
    # get_process_list() 返回 (pid, name) 元组列表
    wechat_processes = [(pid, name) for pid, name in process_list if name.lower() in ['wechat.exe', 'weixin.exe']]
    if not wechat_processes:
        print("[警告] 微信进程未运行，请先启动微信")
        return
    wechat_pid, wechat_name = wechat_processes[0]
    print(f"  [OK] 检测到微信进程: {wechat_name} PID={wechat_pid}")

    # ========== TN-02: 当前登录账号检测 ==========
    print("\n[TN-02] 检测当前登录账号...")
    account_info = detect_current_logged_in_account()
    if not account_info:
        print("[错误] 未检测到登录账号")
        return

    current_account = account_info.get('current_account')
    print(f"  [OK] 当前账号: {current_account}")

    # 查找账号数据目录
    data_dirs = auto_detect_wechat_data_dirs()
    account_dir = None
    for data_dir in data_dirs:
        potential_dir = Path(data_dir) / f"{current_account}_*"
        matches = glob.glob(str(potential_dir))
        if matches:
            account_dir = Path(matches[0]) / "db_storage"
            break

    if not account_dir or not account_dir.exists():
        print(f"[错误] 未找到账号数据目录")
        return

    print(f"  [OK] 数据目录: {account_dir}")

    # ========== TN-03: 密钥获取 ==========
    print("\n[TN-03] 获取数据库密钥...")
    key_store = load_account_keys_store()
    if not key_store:
        print("[错误] 未找到密钥存储，请先运行密钥获取脚本")
        return

    # 查找当前账号的密钥（支持多种匹配方式）
    db_key = None
    accounts = key_store.get('accounts', {})

    # 方式1: 直接匹配账号ID
    if current_account in accounts:
        db_key = accounts[current_account].get('db_key')
    else:
        # 方式2: 通过数据路径匹配
        for account_id, info in accounts.items():
            stored_path = info.get('data_path', '')
            if stored_path:
                # 检查存储路径是否包含当前账号ID
                if current_account in stored_path or account_dir and str(account_dir) in stored_path:
                    db_key = info.get('db_key')
                    print(f"  [INFO] 通过路径匹配找到密钥: {account_id}")
                    break

    if not db_key:
        print(f"[错误] 未找到账号 {current_account} 的密钥")
        print(f"[提示] 可用的账号: {list(accounts.keys())}")
        return

    print(f"  [OK] 密钥已获取: {db_key[:16]}...")

    # ========== TN-04: 数据库解密测试 ==========
    print("\n[TN-04] 测试数据库解密...")
    session_db_path = account_dir / "session" / "session.db"
    if session_db_path.exists():
        # 使用 NamedTemporaryFile 替代不安全的 mktemp
        temp_file = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        temp_db = temp_file.name
        temp_file.close()
        try:
            decryptor = WeChatDatabaseDecryptor(db_key)
            if decryptor.decrypt_database(str(session_db_path), temp_db):
                print(f"  [OK] 数据库解密成功")
            else:
                print(f"  [FAIL] 数据库解密失败")
                return
        finally:
            try:
                os.remove(temp_db)
            except Exception:
                pass

    # ========== 获取群名称映射和当前用户昵称 ==========
    print("\n[准备] 加载群名称映射...")
    contact_db_path = account_dir / "contact" / "contact.db"
    contacts = {}
    current_user_nickname = current_account  # 默认使用账号ID

    if contact_db_path.exists():
        contacts = decrypt_contact_db(contact_db_path, db_key)
        group_count = sum(1 for k in contacts if k.endswith('@chatroom'))

        # 获取当前用户的昵称
        if current_account in contacts:
            current_user_nickname = contacts[current_account].get('display_name', current_account)

        print(f"  [OK] 加载 {len(contacts)} 个联系人，其中 {group_count} 个群聊")
        print(f"  [OK] 当前用户昵称: {current_user_nickname}")

    # 列出群聊模式
    if args.list:
        print("\n" + "=" * 60)
        print("可用群聊列表:")
        print("=" * 60)

        groups = {k: v.get('display_name', k) for k, v in contacts.items() if k.endswith('@chatroom')}
        sorted_groups = sorted(groups.items(), key=lambda x: x[1])

        for i, (group_id, group_name) in enumerate(sorted_groups, 1):
            try:
                # 过滤掉无法编码的字符
                safe_name = group_name.encode('gbk', errors='replace').decode('gbk')
                print(f"  {i:4d}. {safe_name}")
            except Exception:
                print(f"  {i:4d}. [编码错误]")

        print(f"\n共 {len(groups)} 个群聊")
        return

    # 指定群监听模式
    if args.group:
        # 查找群ID
        group_id = None
        group_name = None

        for gid, info in contacts.items():
            if gid.endswith('@chatroom'):
                display_name = info.get('display_name', '') if isinstance(info, dict) else str(info)
                if args.group == gid or args.group == display_name or args.group in display_name:
                    group_id = gid
                    group_name = display_name
                    break

        if not group_id:
            print(f"[错误] 未找到群: {args.group}")
            return

        print(f"\n[TN-05/06] 监听群: {group_name}")

        if args.realtime:
            # 实时监听模式
            monitor_group_realtime(
                account_dir, db_key, group_id, group_name,
                contacts, args.interval,
                current_account, current_user_nickname
            )
        else:
            # 获取历史消息
            print("\n" + "=" * 60)
            print(f"历史消息 - {group_name}")
            print("=" * 60)

            # 优先使用 WCDB
            session_db_path = account_dir / "session" / "session.db"
            try:
                handle = wcdb_open_account(str(session_db_path), db_key)
                if handle > 0:
                    messages = get_group_messages_via_wcdb(
                        handle, group_id, contacts, args.limit,
                        current_account, current_user_nickname
                    )
                    wcdb_close_account(handle)
                else:
                    messages = get_group_messages_from_db(account_dir, db_key, group_id, contacts, args.limit)
            except Exception:
                messages = get_group_messages_from_db(account_dir, db_key, group_id, contacts, args.limit)

            if not messages:
                print("\n  暂无文本消息")
            else:
                print()
                for msg in messages:
                    time_str = format_time(msg.get('create_time'))
                    sender = msg.get('sender_display', '未知')
                    content = msg.get('content', '')
                    print(f"[{time_str}] {sender}")
                    print(f"  {content}")
                    print()

        return

    # 默认：显示帮助
    print("\n使用方法:")
    print("  python src/monitor_group_simple.py --list           # 列出所有群聊")
    print("  python src/monitor_group_simple.py -g 群名称        # 查看历史消息")
    print("  python src/monitor_group_simple.py -g 群名称 -r     # 实时监听")
    print("  python src/monitor_group_simple.py -g 群名称 -r -i 5  # 5秒轮询间隔")


if __name__ == "__main__":
    main()
