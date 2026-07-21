#!/usr/bin/env python3
"""
微信群消息监听系统 - 主程序入口

单一可执行文件的完整CLI菜单系统。
包含所有功能：群聊列表、实时监听、历史消息、数据库解密、密钥管理。

使用方法:
    双击运行或在命令行执行
"""

import sys
import os
from pathlib import Path

# 添加项目路径（开发环境）
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).parent))

from wechat_decrypt_tool.exe_logging import setup_exe_logging, get_exe_logger
from wechat_decrypt_tool.constants import (
    ErrorCode, POLL_INTERVAL_DEFAULT, POLL_INTERVAL_MIN, POLL_INTERVAL_MAX, ZSTD_MAGIC
)
# 导入新的初始化等待器和密钥获取服务
from wechat_decrypt_tool.wechat_waiter import WeChatWaiter
from wechat_decrypt_tool.key_service_retry import KeyAcquisitionService

# 初始化日志
setup_exe_logging()
logger = get_exe_logger(__name__)


class WeChatMonitorApp:
    """微信群消息监听应用"""

    def __init__(self):
        self.pid = None
        self.account_id = None
        self.data_path = None
        self.db_key = None
        self.handle = None
        self.groups = []
        self.running = True
        # 初始化等待器和服务
        self.waiter = WeChatWaiter(verbose=True)
        self.key_service = KeyAcquisitionService(
            max_retries=3,
            retry_interval=3.0,
            verbose=True
        )

    def clear_screen(self):
        """清屏 - 兼容 Windows 终端"""
        import os
        os.system('cls' if os.name == 'nt' else 'clear')

    def print_banner(self):
        """显示Banner"""
        print()
        print("=" * 60)
        print("          微信群消息监听系统 v1.0")
        print("=" * 60)
        print()

    def print_menu(self):
        """显示主菜单"""
        self.print_banner()
        print("  [1] 查看群聊列表")
        print("  [2] 开始监控群聊")
        print("  [3] 查看历史消息")
        print("  [4] 解密数据库")
        print("  [5] 密钥管理")
        print("  [6] 查看系统状态")
        print("  [0] 退出程序")
        print()

    def print_status_bar(self):
        """显示状态栏"""
        status = []
        if self.pid:
            status.append(f"微信PID: {self.pid}")
        if self.account_id:
            status.append(f"账号: {self.account_id[:15]}..." if len(self.account_id) > 15 else f"账号: {self.account_id}")
        if self.handle:
            status.append("WCDB: 已连接")
        else:
            status.append("WCDB: 未连接")

        if status:
            print(f"  状态: {' | '.join(status)}")
            print()

    def input_choice(self, prompt="请选择"):
        """获取用户输入"""
        try:
            return input(f"  {prompt}: ").strip()
        except (EOFError, KeyboardInterrupt):
            return '0'

    def pause(self):
        """暂停等待用户按键"""
        print()
        input("  按 Enter 键继续...")

    # ==================== TN-01: 进程检测 ====================

    def check_wechat_process(self):
        """检测微信进程"""
        logger.info("[TN-01] 检测微信进程...")

        from wechat_decrypt_tool.wechat_detection import get_process_list, get_process_exe_path

        process_list = get_process_list()
        wechat_processes = []

        for pid, process_name in process_list:
            if process_name.lower() in ['weixin.exe', 'wechat.exe']:
                exe_path = get_process_exe_path(pid)
                wechat_processes.append({
                    'pid': pid,
                    'name': process_name,
                    'exe': exe_path or ''
                })

        if wechat_processes:
            self.pid = wechat_processes[0]['pid']
            logger.info(f"[TN-01] 检测到微信进程: PID={self.pid}")
            return True
        else:
            logger.warning(f"[TN-01] {ErrorCode.ERR_PROC_001}")
            return False

    # ==================== TN-02: 账号检测 ====================

    def detect_account(self):
        """检测当前登录账号"""
        logger.info("[TN-02] 检测当前登录账号...")

        from wechat_decrypt_tool.wechat_detection import (
            detect_current_logged_in_account,
            auto_detect_wechat_data_dirs
        )

        detected_dirs = auto_detect_wechat_data_dirs()
        if not detected_dirs:
            logger.error(f"[TN-02] {ErrorCode.ERR_ACCOUNT_003}")
            return False

        result = detect_current_logged_in_account()

        if result.get('current_account'):
            self.account_id = result['current_account']
            self.data_path = detected_dirs[0]
            logger.info(f"[TN-02] 检测到账号: {self.account_id}")
            return True
        else:
            self.data_path = detected_dirs[0]
            logger.warning("[TN-02] 未检测到账号信息，使用默认目录")
            return True

    # ==================== TN-03: 密钥获取 ====================

    def get_key(self):
        """获取数据库密钥（带重试机制）"""
        logger.info("[TN-03] 获取数据库密钥...")

        # 使用新的密钥获取服务
        key = self.key_service.get_stored_key(self.account_id)
        if key:
            self.db_key = key
            logger.info("[TN-03] 使用已保存密钥")
            return True

        # 如果没有存储的密钥，尝试从内存获取
        if self.pid:
            # 查找数据库文件用于验证密钥
            db_file_path = self._find_any_db_file()
            if db_file_path:
                success, key = self.key_service.acquire_key_with_retry(
                    account_id=self.account_id or '',
                    pid=self.pid,
                    db_file_path=db_file_path
                )
                if success and key:
                    self.db_key = key
                    logger.info("[TN-03] 密钥获取成功")
                    return True

        logger.warning(f"[TN-03] {ErrorCode.ERR_KEY_002}")
        return False

    def _find_any_db_file(self):
        """查找任意一个数据库文件用于验证密钥"""
        if not self.data_path:
            return None

        db_storage = Path(self.data_path) / 'db_storage'
        if not db_storage.exists():
            # 尝试其他路径
            db_storage = Path(self.data_path)

        # 查找任意 .db 文件
        for db_file in db_storage.glob('**/*.db'):
            if db_file.name not in ['WxFileIndex.db', 'x_info.db']:
                return str(db_file)

        return None

    # ==================== TN-05: WCDB连接 ====================

    def open_wcdb(self):
        """打开WCDB连接"""
        logger.info("[TN-05] 打开WCDB连接...")

        if not self.db_key:
            logger.error(f"[TN-05] {ErrorCode.ERR_WCDB_002}")
            return False

        from wechat_decrypt_tool.wcdb_realtime import open_account, WCDBRealtimeError

        session_db_path = self._find_session_db()
        if not session_db_path:
            logger.error(f"[TN-05] {ErrorCode.ERR_WCDB_001}")
            return False

        try:
            self.handle = open_account(session_db_path, self.db_key)
            if self.handle and self.handle > 0:
                logger.info(f"[TN-05] WCDB连接成功, handle={self.handle}")
                return True
            else:
                logger.error(f"[TN-05] {ErrorCode.ERR_WCDB_003}")
                return False
        except WCDBRealtimeError as e:
            logger.error(f"[TN-05] WCDB连接失败: {e}")
            return False

    def _find_session_db(self):
        """查找session.db路径"""
        if not self.data_path:
            return None

        # 正确的路径顺序（按优先级）
        session_paths = [
            Path(self.data_path) / 'db_storage' / 'session' / 'session.db',  # 标准路径
            Path(self.data_path) / 'session' / 'session.db',  # 备用路径
            Path(self.data_path) / 'db_storage' / 'session.db',  # 旧版路径
            Path(self.data_path) / 'session.db',  # 最简路径
        ]

        for path in session_paths:
            if path.exists():
                logger.debug(f"[TN-05] 找到session.db: {path}")
                return str(path)

        logger.warning(f"[TN-05] 未找到session.db，搜索路径: {self.data_path}")
        return None

    # ==================== 功能菜单 ====================

    def _load_group_display_names(self):
        """从 contact.db 加载群昵称映射（通过解密数据库）"""
        if not self.data_path or not self.db_key:
            return {}

        try:
            from wechat_core.message_monitor import get_group_names
            return get_group_names(self.db_key, self.data_path)
        except Exception as e:
            logger.warning(f"加载群昵称失败: {e}")
            return {}

    def _load_contact_nicknames(self):
        """从 contact.db 加载联系人昵称映射"""
        if not self.data_path or not self.db_key:
            return {}

        try:
            from wechat_core.db_decryptor import get_decrypted_connection, close_decrypted_connection
            import os

            contact_db = os.path.join(self.data_path, 'db_storage', 'contact', 'contact.db')
            if not os.path.exists(contact_db):
                return {}

            conn = get_decrypted_connection(self.db_key, contact_db)
            if not conn:
                return {}

            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT username, remark, nick_name, alias
                    FROM contact
                """)

                nicknames = {}
                for row in cursor.fetchall():
                    wxid = row['username']
                    # 优先级: 备注 > 昵称 > 别名 > wxid
                    name = row['remark'] or row['nick_name'] or row['alias'] or wxid
                    nicknames[wxid] = name

                return nicknames
            except Exception:
                return {}
            finally:
                close_decrypted_connection(conn)
        except Exception as e:
            logger.warning(f"加载联系人昵称失败: {e}")
            return {}

    def menu_list_groups(self):
        """菜单: 查看群聊列表"""
        self.clear_screen()
        self.print_banner()
        print("  [群聊列表]")
        print()

        if not self._ensure_initialized():
            self.pause()
            return

        from wechat_decrypt_tool.wcdb_realtime import get_sessions, WCDBRealtimeError

        try:
            sessions = get_sessions(self.handle)
            self.groups = [s for s in sessions if s.get('username', '').endswith('@chatroom')]

            if not self.groups:
                print("  暂无群聊")
            else:
                # 加载群昵称
                group_names = self._load_group_display_names()

                for i, group in enumerate(self.groups[:50], 1):
                    group_id = group.get('username', '')
                    # 优先使用 contact.db 中的昵称
                    name = group_names.get(group_id) or group.get('displayName', '') or group_id
                    print(f"  {i:3d}. {name[:40]}")

                if len(self.groups) > 50:
                    print(f"\n  ... 还有 {len(self.groups) - 50} 个群聊")

            print(f"\n  共 {len(self.groups)} 个群聊")

        except WCDBRealtimeError as e:
            print(f"  错误: {e}")
            logger.error(f"获取群聊列表失败: {e}")

        self.pause()

    def menu_monitor_group(self):
        """菜单: 开始监控群聊"""
        self.clear_screen()
        self.print_banner()
        print("  [开始监控]")
        print()

        if not self._ensure_initialized():
            self.pause()
            return

        # 选择群聊
        if not self.groups:
            print("  请先查看群聊列表")
            self.pause()
            return

        # 加载群昵称
        group_names = self._load_group_display_names()

        # 搜索群聊
        print("  请输入群名称关键词（直接回车显示全部）:")
        print()
        keyword = self.input_choice("关键词").strip().lower()

        # 过滤匹配的群聊
        if keyword:
            matched_groups = []
            for group in self.groups:
                group_id = group.get('username', '')
                # 优先使用 contact.db 中的昵称，其次使用 displayName
                name = group_names.get(group_id) or group.get('displayName', '') or group_id
                if keyword in name.lower() or keyword in group_id.lower():
                    matched_groups.append(group)
            
            if not matched_groups:
                print(f"\n  未找到包含 '{keyword}' 的群聊")
                self.pause()
                return
            
            print(f"\n  找到 {len(matched_groups)} 个匹配的群聊:")
        else:
            matched_groups = self.groups
            print(f"\n  共 {len(matched_groups)} 个群聊:")

        print()
        for i, group in enumerate(matched_groups[:20], 1):
            group_id = group.get('username', '')
            name = group_names.get(group_id) or group.get('displayName', '') or group_id
            print(f"  {i:2d}. {name[:35]}")

        if len(matched_groups) > 20:
            print(f"\n  ... 还有 {len(matched_groups) - 20} 个群聊")

        print()
        choice = self.input_choice("请输入群聊编号 (0返回)")

        if choice == '0':
            return

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(matched_groups):
                target_group = matched_groups[idx]
                group_id = target_group.get('username', '')
                group_name = group_names.get(group_id) or target_group.get('displayName', '') or group_id

                self._start_monitoring(group_id, group_name)
        except ValueError:
            print("  无效的输入")

    def _start_monitoring(self, group_id, group_name):
        """开始监控"""
        import time
        from datetime import datetime
        from wechat_decrypt_tool.wcdb_realtime import get_messages, WCDBRealtimeError
        from wechat_decrypt_tool.message_storage import get_message_storage

        self.clear_screen()
        print()
        print("=" * 60)
        print(f"  监控群聊: {group_name}")
        print(f"  群ID: {group_id}")
        print("  按 Ctrl+C 停止监控")
        print("=" * 60)
        print()

        storage = get_message_storage()
        last_time = 0.0
        interval = POLL_INTERVAL_DEFAULT
        # 已处理的消息ID集合（去重）
        processed_msgs = set()
        # 加载联系人昵称映射
        contact_nicknames = self._load_contact_nicknames()

        # 先获取并显示最近20条历史消息
        try:
            initial_messages = get_messages(self.handle, group_id, limit=50)
            if initial_messages:
                # 收集可显示的文字消息
                text_messages = []
                filtered_count = 0
                
                for msg in initial_messages:
                    create_time = msg.get('create_time', 0)
                    if isinstance(create_time, str):
                        try:
                            create_time = float(create_time)
                        except ValueError:
                            create_time = 0
                    
                    content = self._decode_message(msg.get('message_content', ''))
                    if not self._is_text_message(content):
                        filtered_count += 1
                        continue
                    
                    sender_wxid = msg.get('sender_username', '未知')
                    sender = contact_nicknames.get(sender_wxid, sender_wxid)
                    send_time = datetime.fromtimestamp(create_time)
                    
                    text_messages.append({
                        'create_time': create_time,
                        'sender': sender,
                        'content': content,
                        'send_time': send_time,
                        'sender_wxid': sender_wxid
                    })
                
                # 按时间降序排序（新消息在上面）
                text_messages.sort(key=lambda m: m['create_time'], reverse=True)
                
                # 显示消息
                for msg in text_messages:
                    send_time_str = msg['send_time'].strftime('%Y-%m-%d %H:%M:%S')
                    print(f"  [{send_time_str}] {msg['sender']}: {msg['content'][:100]}")
                    
                    # 记录已处理的消息
                    msg_key = f"{msg['create_time']}_{msg['sender_wxid']}"
                    processed_msgs.add(msg_key)
                
                # 更新 last_time 为最新消息时间
                if text_messages:
                    last_time = text_messages[0]['create_time']
                
                if text_messages:
                    print()  # 空行分隔历史消息和新消息
                    print(f"  --- 以上{len(text_messages)}条历史消息，过滤{filtered_count}条非文字消息 ---")
                    print()
                else:
                    print(f"  近期无文字消息（过滤{filtered_count}条非文字消息）")
                    print()
        except Exception as e:
            logger.warning(f"获取历史消息失败: {e}")

        try:
            while self.running:
                time.sleep(interval)

                messages = get_messages(self.handle, group_id, limit=30)
                # 确保 create_time 是数值类型，并去重
                new_messages = []
                for m in messages:
                    create_time = m.get('create_time', 0)
                    if isinstance(create_time, str):
                        try:
                            create_time = float(create_time)
                        except ValueError:
                            create_time = 0
                    if create_time > last_time:
                        # 使用时间戳+发送者作为唯一标识
                        sender = m.get('sender_username', '')
                        msg_key = f"{create_time}_{sender}"
                        if msg_key not in processed_msgs:
                            processed_msgs.add(msg_key)
                            new_messages.append(m)

                if new_messages:
                    interval = max(POLL_INTERVAL_MIN, interval * 0.8)

                    # 按时间降序排序（新消息在前）
                    new_messages.sort(key=lambda m: m.get('create_time', 0), reverse=True)

                    for msg in new_messages:
                        # 确保 last_time 是数值类型
                        create_time = msg.get('create_time', 0)
                        if isinstance(create_time, str):
                            try:
                                create_time = float(create_time)
                            except ValueError:
                                create_time = 0
                        last_time = create_time
                        content = self._decode_message(msg.get('message_content', ''))
                        
                        # 过滤非文字消息
                        if not self._is_text_message(content):
                            continue
                        
                        sender_wxid = msg.get('sender_username', '未知')
                        # 获取发送者昵称（优先使用备注/昵称）
                        sender = contact_nicknames.get(sender_wxid, sender_wxid)
                        # 时间格式增加年月日
                        send_time = datetime.fromtimestamp(last_time)
                        send_time_str = send_time.strftime('%Y-%m-%d %H:%M:%S')
                        
                        # 显示消息
                        print(f"  [{send_time_str}] {sender}: {content[:100]}")
                        
                        # 保存到数据库
                        storage.save_message(
                            sender_nickname=sender,
                            message_content=content,
                            send_time=send_time,
                            group_name=group_name,
                            group_id=group_id,
                            sender_id=sender_wxid
                        )
                    interval = min(POLL_INTERVAL_MAX, interval * 1.1)

        except KeyboardInterrupt:
            print("\n\n  监控已停止")
        except WCDBRealtimeError as e:
            print(f"\n  错误: {e}")
            logger.error(f"监控错误: {e}")

        self.pause()

    def _is_text_message(self, content: str, debug: bool = False) -> bool:
        """判断是否为可显示的文字消息（过滤纯非文字消息）"""
        if not content or len(content.strip()) < 1:
            return False

        content = content.strip()

        # 过滤超长内容（可能是加密数据或文件ID，正常消息不会这么长）
        if len(content) > 2000:
            if debug:
                print(f"  [DEBUG] 过滤超长内容: {len(content)}字符")
            return False

        # 过滤看起来像加密数据的内容（纯十六进制长串）
        import re
        if re.match(r'^[a-f0-9]{32,}$', content):
            if debug:
                print(f"  [DEBUG] 过滤十六进制: {content[:20]}...")
            return False

        # 过滤纯表情符号消息（只有 [xxx] 格式，如 [捂脸][偷笑]）
        # 但如果内容包含其他文字，则保留
        if re.match(r'^(\[[^\]]+\])+$', content):
            if debug:
                print(f"  [DEBUG] 过滤纯表情: {content[:30]}")
            return False

        # 过滤 XML 格式消息（图片、视频、文件等媒体消息）
        # 检查开头是否是XML
        if content.startswith('<?xml') or content.startswith('<msg>') or content.startswith('<sysmsg'):
            if debug:
                print(f"  [DEBUG] 过滤XML消息: {content[:50]}...")
            return False

        # 检查是否包含常见非文字消息的XML标记
        # 注意：要检查完整内容，不只是前100字符
        media_markers = [
            '<img ', '<img>', '<emoji', '<imghdr', '<videomsg', '<voicemsg',
            '<location', '<appattach', '<appmsg', '<type>', '<datamsg',
        ]
        content_lower = content.lower()
        for marker in media_markers:
            if marker in content_lower:
                if debug:
                    print(f"  [DEBUG] 过滤媒体消息({marker}): {content[:50]}...")
                return False

        return True

    def _decode_message(self, raw_content):
        """解码消息内容"""
        import zstandard as zstd
        
        if not raw_content:
            return ''
        
        # 处理字符串类型的压缩数据
        if isinstance(raw_content, str):
            # 检查是否是十六进制编码的压缩数据（以 28b52ffd 开头）
            if raw_content.startswith('28b52ffd') or raw_content.startswith('28B52FFD'):
                try:
                    # 将十六进制字符串转换为字节
                    compressed_bytes = bytes.fromhex(raw_content)
                    decompressor = zstd.ZstdDecompressor()
                    return decompressor.decompress(compressed_bytes).decode('utf-8', errors='replace')
                except Exception:
                    return raw_content
            # 普通字符串直接返回
            return raw_content
        
        # 处理字节类型
        if isinstance(raw_content, bytes):
            if raw_content.startswith(ZSTD_MAGIC):
                try:
                    decompressor = zstd.ZstdDecompressor()
                    return decompressor.decompress(raw_content).decode('utf-8', errors='replace')
                except Exception:
                    return raw_content.decode('utf-8', errors='replace')
            else:
                return raw_content.decode('utf-8', errors='replace')
        
        return str(raw_content)

    def menu_history(self):
        """菜单: 查看历史消息"""
        self.clear_screen()
        self.print_banner()
        print("  [历史消息]")
        print()

        from wechat_decrypt_tool.message_storage import get_message_storage

        storage = get_message_storage()
        groups = storage.get_groups()

        if not groups:
            print("  暂无历史消息")
            self.pause()
            return

        print("  请选择群聊:")
        print()
        for i, g in enumerate(groups[:20], 1):
            print(f"  {i:2d}. {g['group_name'][:30]} ({g['message_count']}条)")

        print()
        choice = self.input_choice("请输入编号 (0返回)")

        if choice == '0':
            return

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(groups):
                group_name = groups[idx]['group_name']
                messages = storage.get_messages(group_name=group_name, limit=50)

                self.clear_screen()
                self.print_banner()
                print(f"  [{group_name}] 历史消息:")
                print()

                for msg in reversed(messages):
                    send_time = msg['send_time']
                    sender = msg['sender_nickname']
                    content = msg['message_content']
                    print(f"  [{send_time}] {sender}: {content[:60]}")

                print()
                self.pause()
        except ValueError:
            print("  无效的输入")
            self.pause()

    def menu_decrypt(self):
        """菜单: 解密数据库"""
        self.clear_screen()
        self.print_banner()
        print("  [解密数据库]")
        print()

        if not self._ensure_initialized():
            self.pause()
            return

        print("  正在解密数据库...")

        from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor
        from wechat_decrypt_tool.exe_logging import get_exe_dir

        output_dir = get_exe_dir() / 'decrypted'
        output_dir.mkdir(exist_ok=True)

        decryptor = WeChatDatabaseDecryptor(self.db_key)

        db_storage = Path(self.data_path) / 'db_storage' if self.data_path else None
        if not db_storage or not db_storage.exists():
            print("  错误: 数据目录不存在")
            self.pause()
            return

        success_count = 0
        db_files = list(db_storage.glob('*.db'))[:10]

        for db_file in db_files:
            try:
                output_path = output_dir / db_file.name
                if decryptor.decrypt_database(str(db_file), str(output_path)):
                    success_count += 1
                    print(f"  ✓ {db_file.name}")
            except Exception as e:
                print(f"  ✗ {db_file.name}: {e}")

        print(f"\n  解密完成: {success_count}/{len(db_files)} 个数据库")
        print(f"  输出目录: {output_dir}")

        self.pause()

    def menu_keys(self):
        """菜单: 密钥管理"""
        self.clear_screen()
        self.print_banner()
        print("  [密钥管理]")
        print()

        from wechat_decrypt_tool.key_store import load_account_keys_store

        store = load_account_keys_store()

        if not store or not store.get('accounts'):
            print("  暂无已保存的密钥")
            self.pause()
            return

        accounts = store.get('accounts', {})
        print(f"  已保存 {len(accounts)} 个账号密钥:")
        print()

        for i, (account_id, data) in enumerate(accounts.items(), 1):
            nickname = data.get('nickname', '未知')
            key_preview = data.get('db_key', '')[:16] + '...'
            print(f"  {i}. {nickname} ({account_id[:20]}...)")
            print(f"     密钥: {key_preview}")

        print()
        self.pause()

    def menu_status(self):
        """菜单: 系统状态"""
        self.clear_screen()
        self.print_banner()
        print("  [系统状态]")
        print()

        print(f"  微信进程: {'运行中 (PID=' + str(self.pid) + ')' if self.pid else '未检测到'}")
        print(f"  当前账号: {self.account_id or '未检测到'}")
        print(f"  数据目录: {self.data_path or '未检测到'}")
        print(f"  密钥状态: {'已获取' if self.db_key else '未获取'}")
        print(f"  WCDB连接: {'已连接 (handle=' + str(self.handle) + ')' if self.handle else '未连接'}")
        print(f"  群聊数量: {len(self.groups)}")
        print()

        from wechat_decrypt_tool.exe_logging import get_log_file_path
        print(f"  日志文件: {get_log_file_path()}")
        print()

        self.pause()

    def _ensure_initialized(self):
        """确保系统已初始化（带等待机制）"""
        # 阶段1: 等待微信进程
        if not self.pid:
            print("\n[初始化] 等待微信进程...")
            self.pid = self.waiter.wait_for_process(timeout=60)
            if not self.pid:
                print("  错误: 请先启动微信并登录")
                return False
            print(f"  [OK] 微信进程 PID={self.pid}")

        # 阶段2: 检测账号
        if not self.account_id:
            print("\n[初始化] 检测账号...")
            if not self.detect_account():
                print("  错误: 账号检测失败")
                return False

        # 阶段3: 等待数据目录（如果是新账号）
        if self.account_id and not self.data_path:
            print("\n[初始化] 等待数据目录...")
            db_storage = self.waiter.wait_for_data_dir(self.account_id, timeout=30)
            if db_storage:
                self.data_path = str(db_storage.parent)

        # 阶段4: 密钥获取（带重试）
        if not self.db_key:
            print("\n[初始化] 获取密钥...")
            if not self.get_key():
                print("  错误: 密钥获取失败")
                print("  提示: 请确保微信已完全登录，然后重新尝试")
                return False

        # 阶段5: 连接数据库
        if not self.handle:
            print("\n[初始化] 连接数据库...")
            if not self.open_wcdb():
                print("  错误: WCDB连接失败")
                return False

        # 加载群列表
        if not self.groups:
            from wechat_decrypt_tool.wcdb_realtime import get_sessions, WCDBRealtimeError
            try:
                sessions = get_sessions(self.handle)
                self.groups = [s for s in sessions if s.get('username', '').endswith('@chatroom')]
            except WCDBRealtimeError:
                pass

        print("\n[初始化] 完成！")
        return True

    def run(self):
        """运行主循环"""
        print("\n" + "=" * 60)
        print("  微信群消息监听系统 - 启动中")
        print("=" * 60)

        # 初始化检查（带等待机制）
        self.check_wechat_process()
        if self.pid:
            self.detect_account()

            # 等待数据目录就绪
            if self.account_id:
                print(f"\n[等待] 等待微信初始化...")
                db_storage = self.waiter.wait_for_data_dir(self.account_id, timeout=30)
                if db_storage:
                    self.data_path = str(db_storage.parent)

            # 尝试获取密钥
            self.get_key()

            if self.db_key:
                self.open_wcdb()

        print("\n[就绪] 系统初始化完成")

        while self.running:
            self.clear_screen()
            self.print_menu()
            self.print_status_bar()

            choice = self.input_choice("请选择")

            if choice == '1':
                self.menu_list_groups()
            elif choice == '2':
                self.menu_monitor_group()
            elif choice == '3':
                self.menu_history()
            elif choice == '4':
                self.menu_decrypt()
            elif choice == '5':
                self.menu_keys()
            elif choice == '6':
                self.menu_status()
            elif choice == '0':
                self.running = False
            else:
                print("  无效的输入")
                self.pause()

        self.clear_screen()
        print()
        print("  感谢使用，再见！")
        print()


def main():
    """主函数"""
    try:
        app = WeChatMonitorApp()
        app.run()
    except Exception as e:
        logger.exception(f"程序异常: {e}")
        print(f"\n  程序异常: {e}")
        input("  按 Enter 键退出...")
        sys.exit(1)


if __name__ == '__main__':
    main()
