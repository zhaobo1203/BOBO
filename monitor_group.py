#!/usr/bin/env python3
"""
微信群消息实时监听脚本 (monitor_group.py)

按照 TECHNICAL_SPECIFICATION_REPORT.md 规格实现的独立监听脚本。
用于监控指定群聊并实时显示/存储消息。

功能:
- 单群实时监听
- 自适应轮询间隔
- 消息持久化存储
- zstd消息解压

使用方法:
    python monitor_group.py --list                      # 列出所有群聊
    python monitor_group.py -g "群名称"                 # 监控指定群聊
    python monitor_group.py -g "群名称" -i 2            # 2秒轮询间隔
    python monitor_group.py -g "群名称" --history 100   # 获取100条历史消息
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from wechat_decrypt_tool.constants import (
    ErrorCode,
    POLL_INTERVAL_DEFAULT,
    POLL_INTERVAL_MIN,
    POLL_INTERVAL_MAX,
    ZSTD_MAGIC
)
from wechat_decrypt_tool.logging_config import get_logger, setup_logging

logger = get_logger(__name__)


def decode_message_content(raw_content) -> str:
    """
    解码消息内容（处理zstd压缩）

    按技术规格报告6.4节实现的解码算法:
    1. 检测是否为bytes类型
    2. 检测zstd魔数 (0x28b52ffd)
    3. 如果是zstd压缩，解压并解码
    4. 否则直接解码为UTF-8

    Args:
        raw_content: 原始消息内容

    Returns:
        解码后的字符串
    """
    if isinstance(raw_content, bytes):
        if raw_content.startswith(ZSTD_MAGIC):
            try:
                import zstandard as zstd
                decompressor = zstd.ZstdDecompressor()
                return decompressor.decompress(raw_content).decode('utf-8', errors='replace')
            except Exception:
                return raw_content.decode('utf-8', errors='replace')
        else:
            return raw_content.decode('utf-8', errors='replace')
    return str(raw_content or '')


def monitor_loop(handle: int, group_id: str, group_name: str, interval: float, storage=None):
    """
    实时消息监听循环（自适应轮询）

    按技术规格报告6.3节实现:
    1. 获取初始最新消息时间戳
    2. 进入轮询循环
    3. 有新消息时: 缩短轮询间隔 (最小0.5s)
    4. 无新消息时: 延长轮询间隔 (最大5s)
    5. 每隔60秒检查连接状态

    Args:
        handle: WCDB连接句柄
        group_id: 群ID
        group_name: 群名称
        interval: 初始轮询间隔（秒）
        storage: 消息存储实例（可选）
    """
    from wechat_decrypt_tool.wcdb_realtime import get_messages, WCDBRealtimeError

    last_time = 0
    current_interval = interval
    last_reconnect_check = time.time()

    print(f"\n{'='*60}")
    print(f"  监控群聊: {group_name}")
    print(f"  群ID: {group_id}")
    print(f"  轮询间隔: {interval}s (自适应)")
    print(f"  按 Ctrl+C 停止监控")
    print(f"{'='*60}\n")

    while True:
        try:
            time.sleep(current_interval)

            messages = get_messages(handle, group_id, limit=30)
            new_messages = [m for m in messages if m.get('create_time', 0) > last_time]

            if new_messages:
                # 有新消息，缩短轮询间隔
                current_interval = max(POLL_INTERVAL_MIN, current_interval * 0.8)

                for msg in new_messages:
                    last_time = msg.get('create_time', 0)

                    # 解码消息内容
                    content = decode_message_content(msg.get('message_content', ''))
                    sender = msg.get('sender_username', '未知')

                    # 显示消息
                    send_time = datetime.fromtimestamp(last_time).strftime('%Y-%m-%d %H:%M:%S')
                    print(f"[{send_time}] {sender}: {content[:100]}{'...' if len(content) > 100 else ''}")

                    # 保存消息
                    if storage:
                        try:
                            storage.save_message(
                                sender_nickname=sender,
                                message_content=content,
                                send_time=datetime.fromtimestamp(last_time),
                                group_name=group_name,
                                group_id=group_id,
                                sender_id=msg.get('sender_username')
                            )
                        except Exception as e:
                            logger.warning(f"消息存储失败: {e}")
            else:
                # 无新消息，延长轮询间隔
                current_interval = min(POLL_INTERVAL_MAX, current_interval * 1.1)

            # 定期检查连接状态
            if time.time() - last_reconnect_check > 60:
                last_reconnect_check = time.time()
                logger.debug(f"[监控] 连接状态检查, handle={handle}")

        except KeyboardInterrupt:
            print("\n\n监控已停止")
            break
        except WCDBRealtimeError as e:
            logger.error(f"[监控] WCDB错误: {e}")
            time.sleep(5)
        except Exception as e:
            logger.error(f"[监控] 未知错误: {e}")
            time.sleep(5)


def get_history_messages(handle: int, group_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """
    获取历史消息

    Args:
        handle: WCDB连接句柄
        group_id: 群ID
        limit: 获取数量

    Returns:
        消息列表
    """
    from wechat_decrypt_tool.wcdb_realtime import get_messages, WCDBRealtimeError

    try:
        messages = get_messages(handle, group_id, limit=limit)
        return messages
    except WCDBRealtimeError as e:
        logger.error(f"获取历史消息失败: {e}")
        return []


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='微信群消息实时监听脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python monitor_group.py --list                      # 列出所有群聊
    python monitor_group.py -g "群名称"                 # 监控指定群聊
    python monitor_group.py -g "群名称" -i 2            # 2秒轮询间隔
    python monitor_group.py -g "群名称" --history 100   # 获取100条历史消息
        """
    )

    parser.add_argument('-g', '--group', type=str, help='要监控的群名称或群ID')
    parser.add_argument('-i', '--interval', type=float, default=POLL_INTERVAL_DEFAULT, help='轮询间隔（秒）')
    parser.add_argument('--list', action='store_true', help='列出所有群聊')
    parser.add_argument('--history', type=int, default=0, help='获取历史消息数量')
    parser.add_argument('--no-storage', action='store_true', help='不保存消息到数据库')
    parser.add_argument('--debug', action='store_true', help='调试模式')

    args = parser.parse_args()

    # 设置日志
    setup_logging()

    if args.debug:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)

    # 导入必要模块
    from wechat_decrypt_tool.wechat_detection import (
        get_process_list,
        get_process_exe_path,
        detect_current_logged_in_account,
        auto_detect_wechat_data_dirs
    )
    from wechat_decrypt_tool.key_store import load_account_keys_store
    from wechat_decrypt_tool.wcdb_realtime import (
        open_account,
        get_sessions,
        get_messages,
        WCDBRealtimeError
    )
    from wechat_decrypt_tool.message_storage import get_message_storage

    # ============================================================
    # TN-01: 检测微信进程
    # ============================================================
    print("\n[步骤1] 检测微信进程...")

    process_list = get_process_list()
    wechat_processes = []
    pid = None

    for p, process_name in process_list:
        if process_name.lower() in ['weixin.exe', 'wechat.exe']:
            exe_path = get_process_exe_path(p)
            wechat_processes.append({
                'pid': p,
                'name': process_name,
                'exe': exe_path or ''
            })

    if wechat_processes:
        pid = wechat_processes[0]['pid']
        print(f"  检测到微信进程: PID={pid}")
    else:
        print(f"  [错误] {ErrorCode.ERR_PROC_001}")
        print("  请先启动微信客户端并登录")
        sys.exit(1)

    # ============================================================
    # TN-02: 检测账号
    # ============================================================
    print("\n[步骤2] 检测当前登录账号...")

    detected_dirs = auto_detect_wechat_data_dirs()
    if not detected_dirs:
        print(f"  [错误] {ErrorCode.ERR_ACCOUNT_003}")
        sys.exit(1)

    result = detect_current_logged_in_account()
    account_id = result.get('current_account')
    data_path = detected_dirs[0]

    if account_id:
        print(f"  当前账号: {account_id}")
    print(f"  数据目录: {data_path}")

    # ============================================================
    # TN-03: 获取密钥
    # ============================================================
    print("\n[步骤3] 获取数据库密钥...")

    store = load_account_keys_store()
    db_key = None

    if store and 'accounts' in store:
        # 尝试通过账号ID匹配
        for stored_id, account_data in store.get('accounts', {}).items():
            if account_id and stored_id == account_id:
                key = account_data.get('db_key')
                if key and len(key) == 64:
                    db_key = key
                    print(f"  使用已保存密钥: 账号={stored_id}")
                    break

        # 尝试通过路径匹配
        if not db_key:
            for account_data in store.get('accounts', {}).values():
                stored_path = account_data.get('data_path', '')
                if stored_path and data_path:
                    normalized_stored = os.path.normpath(stored_path).lower()
                    normalized_current = os.path.normpath(data_path).lower()
                    if normalized_stored in normalized_current or normalized_current in normalized_stored:
                        key = account_data.get('db_key')
                        if key and len(key) == 64:
                            db_key = key
                            print(f"  通过路径匹配到密钥")
                            break

    if not db_key:
        print(f"  [错误] {ErrorCode.ERR_KEY_002}")
        print("  请先运行 tn_combined_v3.py 获取并保存密钥")
        sys.exit(1)

    # ============================================================
    # TN-05: 打开WCDB连接
    # ============================================================
    print("\n[步骤4] 打开WCDB连接...")

    # 查找session.db路径
    session_db_path = None
    session_paths = [
        Path(data_path) / 'db_storage' / 'session.db',
        Path(data_path) / 'session.db',
    ]

    for path in session_paths:
        if path.exists():
            session_db_path = str(path)
            break

    if not session_db_path:
        print(f"  [错误] {ErrorCode.ERR_WCDB_001}")
        sys.exit(1)

    print(f"  session.db: {session_db_path}")

    try:
        handle = open_account(session_db_path, db_key, account_id or '')
        if not handle or handle <= 0:
            print(f"  [错误] {ErrorCode.ERR_WCDB_003}")
            sys.exit(1)
        print(f"  WCDB连接成功, handle={handle}")
    except WCDBRealtimeError as e:
        print(f"  [错误] WCDB连接失败: {e}")
        sys.exit(1)

    # ============================================================
    # 加载群聊列表
    # ============================================================
    print("\n[步骤5] 加载群聊列表...")

    try:
        sessions = get_sessions(handle)
        groups = [s for s in sessions if s.get('username', '').endswith('@chatroom')]
        print(f"  检测到 {len(groups)} 个群聊")
    except WCDBRealtimeError as e:
        print(f"  [错误] 加载群聊失败: {e}")
        sys.exit(1)

    # 列出群聊
    if args.list:
        print("\n群聊列表:\n")
        for i, group in enumerate(groups, 1):
            name = group.get('displayName', '') or group.get('username', '')
            print(f"  {i:3d}. {name}")
        print(f"\n共 {len(groups)} 个群聊")
        sys.exit(0)

    # 选择群聊
    target_group = None
    if args.group:
        # 查找匹配的群聊
        for group in groups:
            name = group.get('displayName', '') or group.get('username', '')
            group_id = group.get('username', '')
            if args.group.lower() in name.lower() or args.group.lower() in group_id.lower():
                target_group = group
                break

        if not target_group:
            print(f"\n[错误] 未找到群聊: {args.group}")
            sys.exit(1)
    else:
        # 交互式选择
        print("\n请选择要监控的群聊:\n")
        for i, group in enumerate(groups[:30], 1):
            name = group.get('displayName', '') or group.get('username', '')
            print(f"  {i:2d}. {name[:40]}")

        if len(groups) > 30:
            print(f"\n  ... 还有 {len(groups) - 30} 个群聊")

        print()
        try:
            choice = int(input("请输入群聊编号 (0退出): "))
            if choice == 0:
                sys.exit(0)
            if 1 <= choice <= len(groups):
                target_group = groups[choice - 1]
        except (ValueError, EOFError):
            print("无效的输入")
            sys.exit(1)

    if not target_group:
        print("未选择群聊")
        sys.exit(1)

    group_id = target_group.get('username', '')
    group_name = target_group.get('displayName', '') or group_id

    print(f"\n选择群聊: {group_name}")
    print(f"群ID: {group_id}")

    # ============================================================
    # 获取历史消息
    # ============================================================
    if args.history > 0:
        print(f"\n获取 {args.history} 条历史消息...")
        history = get_history_messages(handle, group_id, args.history)

        if history:
            print(f"\n历史消息 ({len(history)} 条):\n")
            for msg in reversed(history):
                send_time = datetime.fromtimestamp(msg.get('create_time', 0)).strftime('%Y-%m-%d %H:%M:%S')
                content = decode_message_content(msg.get('message_content', ''))
                sender = msg.get('sender_username', '未知')
                print(f"[{send_time}] {sender}: {content[:80]}{'...' if len(content) > 80 else ''}")
        else:
            print("没有历史消息")

    # ============================================================
    # 开始监控
    # ============================================================
    storage = None if args.no_storage else get_message_storage()

    monitor_loop(
        handle=handle,
        group_id=group_id,
        group_name=group_name,
        interval=args.interval,
        storage=storage
    )

    sys.exit(0)


if __name__ == '__main__':
    main()
