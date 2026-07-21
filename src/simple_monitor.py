#!/usr/bin/env python3
"""
微信群消息监听系统 - 简化版一键启动

流程: 启动 → 进程检测 → 账号识别 → 密钥获取 → 数据库解密 → 选择群聊 → 实时监控
"""

import sys
import os
import time
import logging
from pathlib import Path
from datetime import datetime

# 添加项目路径
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).parent))

from wechat_decrypt_tool.exe_logging import setup_exe_logging, get_exe_logger, get_exe_dir
from wechat_decrypt_tool.constants import POLL_INTERVAL_DEFAULT, POLL_INTERVAL_MIN, POLL_INTERVAL_MAX, ZSTD_MAGIC

# 初始化日志
setup_exe_logging()
logger = get_exe_logger(__name__)


class SimpleMonitor:
    """简化版监控器 - 一键启动"""

    def __init__(self):
        self.pid = None
        self.account_id = None
        self.data_path = None
        self.db_key = None
        self.handle = None
        self.groups = []

    def print_header(self):
        """显示头部"""
        print()
        print("=" * 60)
        print("          微信群消息监听系统 v1.0")
        print("=" * 60)
        print()

    def print_step(self, step_name, status, detail=""):
        """显示步骤状态"""
        if status == 'done':
            symbol = "[OK]"
        elif status == 'doing':
            symbol = "[..]"
        else:
            symbol = "[FAIL]"

        line = f"  {symbol} {step_name}"
        if detail:
            line += f": {detail}"
        print(line)

    def step1_detect_process(self):
        """步骤1: 进程检测"""
        print()
        self.print_step("进程检测", "doing")

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
            self.print_step("进程检测", "done", f"PID={self.pid}")
            logger.info(f"[步骤1] 检测到微信进程: PID={self.pid}")
            return True
        else:
            self.print_step("进程检测", "fail", "未检测到微信进程")
            print()
            print("  请先启动微信并登录账号!")
            return False

    def step2_detect_account(self):
        """步骤2: 账号识别"""
        self.print_step("账号识别", "doing")

        from wechat_decrypt_tool.wechat_detection import (
            detect_current_logged_in_account,
            auto_detect_wechat_data_dirs
        )

        detected_dirs = auto_detect_wechat_data_dirs()
        if not detected_dirs:
            self.print_step("账号识别", "fail", "未找到数据目录")
            return False

        result = detect_current_logged_in_account()

        if result.get('current_account'):
            self.account_id = result['current_account']

            # 使用参考项目的方法查找正确的账号目录
            self.data_path = self._find_account_dir_with_db_storage(detected_dirs, self.account_id)

            if not self.data_path:
                # 如果找不到有效的db_storage，使用原始逻辑
                if result.get('data_path'):
                    self.data_path = result['data_path']
                else:
                    self.data_path = self._find_account_dir(detected_dirs, self.account_id)

            account_display = self.account_id[:20] + "..." if len(self.account_id) > 20 else self.account_id
            self.print_step("账号识别", "done", account_display)
            logger.info(f"[步骤2] 检测到账号: {self.account_id}, 数据路径: {self.data_path}")
            return True
        else:
            self.data_path = detected_dirs[0]
            self.print_step("账号识别", "done", "使用默认目录")
            return True

    def _find_account_dir_with_db_storage(self, base_dirs: list, account_id: str):
        """查找包含有效 db_storage 的账号目录（参考项目的方法）"""
        for base_dir in base_dirs:
            base_path = Path(base_dir)
            if not base_path.exists() or not base_path.is_dir():
                continue

            try:
                for sub_dir in base_path.iterdir():
                    if not sub_dir.is_dir():
                        continue

                    # 检查目录名是否包含账号ID
                    if account_id.lower() in sub_dir.name.lower():
                        # 验证 session.db 是否存在
                        test_path = sub_dir / 'db_storage' / 'session' / 'session.db'
                        logger.debug(f"[步骤2] 检查路径: {test_path}, 存在: {test_path.exists()}")
                        if test_path.exists():
                            logger.info(f"[步骤2] 找到有效账号目录: {sub_dir}")
                            return str(sub_dir)
            except (PermissionError, OSError) as e:
                logger.debug(f"[步骤2] 遍历目录失败: {base_dir}, 错误: {e}")
                continue

            # 参考项目: 检查 "WeChat Files" 子目录
            wechat_files_path = base_path / 'WeChat Files'
            if wechat_files_path.exists() and wechat_files_path.is_dir():
                try:
                    for sub_dir in wechat_files_path.iterdir():
                        if not sub_dir.is_dir():
                            continue

                        if account_id.lower() in sub_dir.name.lower():
                            test_path = sub_dir / 'db_storage' / 'session' / 'session.db'
                            logger.debug(f"[步骤2] 检查路径: {test_path}, 存在: {test_path.exists()}")
                            if test_path.exists():
                                logger.info(f"[步骤2] 找到有效账号目录: {sub_dir}")
                                return str(sub_dir)
                except (PermissionError, OSError) as e:
                    logger.debug(f"[步骤2] 遍历WeChat Files目录失败: {e}")
                    continue

        return None

    def _find_account_dir(self, base_dirs: list, account_id: str):
        """查找账号对应的数据目录"""
        for base_dir in base_dirs:
            try:
                for item in os.listdir(base_dir):
                    item_path = os.path.join(base_dir, item)
                    if os.path.isdir(item_path) and item.startswith(account_id):
                        return item_path
            except (PermissionError, OSError):
                continue
        return base_dirs[0] if base_dirs else None

    def step3_get_key(self):
        """步骤3: 密钥获取"""
        self.print_step("密钥获取", "doing")

        import json
        import traceback

        exe_dir = get_exe_dir()
        cwd = Path.cwd()

        # 方法1: Hook注入获取
        logger.info("[步骤3] 尝试Hook注入获取密钥...")

        print()
        print("  [!] 需要重启微信以获取密钥")
        print("  [!] 请在微信重启后手动登录")
        print("  [!] 等待时间最长60秒...")
        print()

        try:
            from wechat_decrypt_tool.key_service import WeChatKeyFetcher

            fetcher = WeChatKeyFetcher()
            logger.info("[步骤3] WeChatKeyFetcher 实例化成功，开始调用 fetch_db_key()...")

            result = fetcher.fetch_db_key()
            logger.info(f"[步骤3] fetch_db_key() 返回结果: {type(result).__name__}, keys={list(result.keys()) if result else 'None'}")

            if result:
                db_key = result.get('key') or result.get('db_key')
                logger.info(f"[步骤3] 提取到的密钥长度: {len(str(db_key)) if db_key else 0}")
                if db_key and len(str(db_key)) == 64:
                    self.db_key = str(db_key).lower()
                    self.print_step("密钥获取", "done", "Hook注入成功")
                    logger.info("[步骤3] Hook注入成功获取密钥")
                    self._save_key()
                    return True
                else:
                    logger.warning(f"[步骤3] Hook返回密钥格式无效: len={len(str(db_key)) if db_key else 0}")
                    print(f"  [!] 密钥格式无效，长度: {len(str(db_key)) if db_key else 0}")

        except ImportError as e:
            logger.error(f"[步骤3] wx_key模块不可用: {e}")
            print(f"  [!] wx_key模块导入失败: {e}")
        except TimeoutError as e:
            logger.error(f"[步骤3] Hook获取密钥超时: {e}")
            print(f"  [!] 获取密钥超时: {e}")
            print("  [!] 请确保在60秒内完成微信登录")
        except RuntimeError as e:
            logger.error(f"[步骤3] Hook运行时错误: {e}")
            print(f"  [!] Hook运行时错误: {e}")
        except Exception as e:
            logger.error(f"[步骤3] Hook注入失败: {e}")
            logger.error(f"[步骤3] 详细错误信息:\n{traceback.format_exc()}")
            print(f"  [!] Hook注入失败: {e}")
            print(f"  [!] 详细信息请查看日志文件")

        # 方法2: 从已保存文件加载
        logger.info("[步骤3] 尝试加载已保存密钥...")

        store = {}
        key_paths = [
            exe_dir / 'output' / 'account_keys.json',
            exe_dir / 'key_store.json',
            cwd / 'output' / 'account_keys.json',
            cwd / 'key_store.json',
        ]

        for key_path in key_paths:
            if key_path.exists():
                try:
                    data = json.loads(key_path.read_text(encoding='utf-8'))
                    if data and 'accounts' in data:
                        store = data
                        break
                except Exception:
                    pass

        if store and 'accounts' in store:
            for account_id, account_data in store.get('accounts', {}).items():
                if account_id == self.account_id:
                    key = account_data.get('db_key')
                    if key and len(key) == 64:
                        self.db_key = key
                        self.print_step("密钥获取", "done", "已从存储加载")
                        logger.info(f"[步骤3] 使用已保存密钥")
                        return True

            for account_data in store.get('accounts', {}).values():
                stored_path = account_data.get('data_path', '')
                if stored_path and self.data_path:
                    normalized_stored = os.path.normpath(stored_path).lower()
                    normalized_current = os.path.normpath(self.data_path).lower()
                    if normalized_stored in normalized_current or normalized_current in normalized_stored:
                        key = account_data.get('db_key')
                        if key and len(key) == 64:
                            self.db_key = key
                            self.print_step("密钥获取", "done", "路径匹配成功")
                            logger.info(f"[步骤3] 路径匹配到密钥")
                            return True

        self.print_step("密钥获取", "fail", "未找到密钥")
        print()
        print("  请先运行密钥获取程序!")
        return False

    def _save_key(self):
        """保存密钥到存储"""
        import json

        exe_dir = get_exe_dir()
        key_store_path = exe_dir / 'output' / 'account_keys.json'

        key_store_path.parent.mkdir(parents=True, exist_ok=True)

        store = {'accounts': {}}
        if key_store_path.exists():
            try:
                store = json.loads(key_store_path.read_text(encoding='utf-8'))
                if 'accounts' not in store:
                    store['accounts'] = {}
            except Exception:
                store = {'accounts': {}}

        if self.account_id:
            store['accounts'][self.account_id] = {
                'db_key': self.db_key,
                'data_path': str(self.data_path),
                'last_updated': datetime.now().isoformat()
            }

        try:
            key_store_path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding='utf-8')
            logger.info(f"[步骤3] 密钥已保存")
        except Exception as e:
            logger.warning(f"[步骤3] 保存密钥失败: {e}")

    def step4_connect_db(self):
        """步骤4: 数据库连接"""
        self.print_step("数据库连接", "doing")

        if not self.db_key:
            self.print_step("数据库连接", "fail", "无密钥")
            return False

        print(f"  等待微信初始化完成...")
        time.sleep(3)

        session_db_path = self._find_session_db()
        if not session_db_path:
            self.print_step("数据库连接", "fail", "session.db不存在")
            return False

        # 首先尝试静态解密（用于获取群聊列表）
        print(f"  使用静态解密方式...")
        logger.info(f"[步骤4] 尝试静态解密方式连接数据库")

        static_success = False
        try:
            if self._connect_via_static_decrypt(session_db_path):
                self.print_step("数据库连接", "done", "静态解密成功")
                logger.info(f"[步骤4] 静态解密连接成功")
                static_success = True
        except Exception as e:
            logger.warning(f"[步骤4] 静态解密失败: {e}")

        # 尝试 WCDB 连接（用于消息获取）
        print(f"  尝试 WCDB 连接...", flush=True)
        logger.info(f"[步骤4] 尝试WCDB实时连接")

        try:
            from wechat_decrypt_tool.wcdb_realtime import open_account, WCDBRealtimeError

            def _connect_wcdb():
                return open_account(session_db_path, self.db_key, timeout=8.0)

            # 使用较短的超时时间，避免长时间等待
            import threading
            result = [None]
            exception = [None]

            def _worker():
                try:
                    result[0] = open_account(session_db_path, self.db_key, timeout=8.0)
                except Exception as e:
                    exception[0] = e

            thread = threading.Thread(target=_worker, daemon=True)
            thread.start()
            thread.join(timeout=10.0)  # 最多等待10秒

            if thread.is_alive():
                # 超时，WCDB 连接未完成
                logger.warning(f"[步骤4] WCDB连接超时(10秒)，使用静态模式")
                self.handle = None
                print(f"  WCDB 连接超时，将使用静态模式", flush=True)
            elif exception[0]:
                # 连接出错
                logger.warning(f"[步骤4] WCDB连接失败: {exception[0]}")
                self.handle = None
                print(f"  WCDB 连接失败: {exception[0]}", flush=True)
            else:
                self.handle = result[0]
                if self.handle and self.handle > 0:
                    logger.info(f"[步骤4] WCDB连接成功，handle={self.handle}")
                    print(f"  WCDB 连接成功", flush=True)
                else:
                    logger.info(f"[步骤4] WCDB连接返回无效句柄")
                    self.handle = None
                    print(f"  WCDB 连接失败", flush=True)
        except Exception as e:
            logger.warning(f"[步骤4] WCDB连接异常: {e}")
            self.handle = None
            print(f"  WCDB 连接异常: {e}", flush=True)

        # 只要静态解密成功，就返回 True
        return static_success

    def _connect_via_static_decrypt(self, session_db_path: str) -> bool:
        """通过静态解密方式连接数据库"""
        import tempfile
        import sqlite3
        from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor

        self.temp_dir = tempfile.mkdtemp(prefix="wechat_monitor_")

        decryptor = WeChatDatabaseDecryptor(self.db_key)
        self.decrypted_session_db = os.path.join(self.temp_dir, "session.db")

        if not decryptor.decrypt_database(session_db_path, self.decrypted_session_db):
            return False

        print(f"  session.db 解密成功")

        contact_db_path = self._find_contact_db()
        if contact_db_path:
            self.decrypted_contact_db = os.path.join(self.temp_dir, "contact.db")
            if decryptor.decrypt_database(contact_db_path, self.decrypted_contact_db):
                print(f"  contact.db 解密成功")
            else:
                self.decrypted_contact_db = None
        else:
            self.decrypted_contact_db = None

        self.use_static_mode = True
        self.static_mode_for_groups_only = True  # 静态解密仅用于获取群聊列表

        # 加载昵称缓存（从 contact.db）
        self._load_nickname_cache()

        try:
            conn = sqlite3.connect(self.decrypted_session_db)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
            cursor.fetchone()
            conn.close()
            return True
        except Exception:
            return False

    def _load_nickname_cache(self):
        """从 contact.db 加载昵称缓存

        建立 wxid -> 昵称 的映射字典
        """
        import sqlite3

        self.nickname_cache = {}

        if not self.decrypted_contact_db or not os.path.exists(self.decrypted_contact_db):
            logger.warning("[昵称缓存] contact.db 不存在，无法加载昵称")
            return

        try:
            conn = sqlite3.connect(self.decrypted_contact_db)
            cursor = conn.cursor()

            # 查询所有联系人
            cursor.execute("""
                SELECT username, nick_name, remark
                FROM contact
            """)

            count = 0
            for row in cursor.fetchall():
                username, nick_name, remark = row
                # 优先使用备注名，其次昵称
                display_name = remark or nick_name or ''
                if display_name and username:
                    self.nickname_cache[username] = display_name
                    count += 1

            conn.close()
            logger.info(f"[昵称缓存] 已加载 {count} 个昵称映射")
            print(f"  已加载 {count} 个联系人昵称")

        except Exception as e:
            logger.warning(f"[昵称缓存] 加载失败: {e}")

    def _get_display_name(self, wxid: str) -> str:
        """获取 wxid 对应的显示名称

        优先从缓存获取，找不到则返回原 wxid
        """
        if hasattr(self, 'nickname_cache') and self.nickname_cache:
            return self.nickname_cache.get(wxid, wxid)
        return wxid

    def _is_non_text_message(self, content: str) -> bool:
        """判断是否为非纯文字消息（需要完全过滤的）

        过滤: 图片、网页链接、ZIP打包文件、视频、语音等
        注意: 表情包标记会被清理，不会被过滤
        """
        if not content or not content.strip():
            return True

        content_stripped = content.strip()

        # XML 格式消息（图片、链接、文件等）- 完全过滤
        if content_stripped.startswith('<?xml') or content_stripped.startswith('<msg'):
            return True

        # 检查是否包含图片标签（即使不是 XML 开头）
        if '<img' in content_stripped.lower():
            return True

        # 检查是否包含其他非文字标签
        non_text_tags = ['<videomsg', '<voicemsg', '<appmsg', '<emoji', '<location']
        for tag in non_text_tags:
            if tag in content_stripped.lower():
                return True

        return False

    def _clean_message_content(self, content: str) -> str:
        """清理消息内容，去除表情包标记，保留文字

        例如: "[太阳]【国金计算机】..." -> "【国金计算机】..."
        例如: "1 半导体...[太阳]晶圆厂..." -> "1 半导体...晶圆厂..."
        """
        if not content:
            return ""

        import re

        # 去除所有位置的表情包标记（如 [太阳]、[红包] 等）
        # 匹配 [...] 格式的表情包，包括前后有空格的情况
        cleaned = re.sub(r'\s*\[[^\]]+\]\s*', ' ', content)

        # 清理多余的空格
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        # 如果清理后为空，返回原始内容
        if not cleaned.strip():
            return content.strip()

        return cleaned.strip()

    def _find_contact_db(self) -> str | None:
        """查找contact.db路径"""
        if not self.data_path:
            return None

        contact_paths = [
            Path(self.data_path) / 'db_storage' / 'contact' / 'contact.db',
            Path(self.data_path) / 'db_storage' / 'contact.db',
        ]

        for path in contact_paths:
            if path.exists():
                return str(path)

        return None

    def _find_session_db(self):
        """查找session.db路径"""
        if not self.data_path:
            return None

        session_paths = [
            Path(self.data_path) / 'db_storage' / 'session' / 'session.db',
            Path(self.data_path) / 'db_storage' / 'session.db',
            Path(self.data_path) / 'session.db',
        ]

        data_path_obj = Path(self.data_path)
        if data_path_obj.exists():
            try:
                for item in data_path_obj.iterdir():
                    if item.is_dir() and not item.name.startswith('.'):
                        if item.name.startswith('wxid_') or item.name.startswith('wl_'):
                            db_path = item / 'db_storage' / 'session' / 'session.db'
                            if db_path.exists():
                                session_paths.append(db_path)
            except (PermissionError, OSError):
                pass

        for path in session_paths:
            if path.exists():
                return str(path)

        return None

    def step5_select_group(self):
        """步骤5: 选择群聊"""
        print()

        if getattr(self, 'use_static_mode', False):
            return self._select_group_static()
        else:
            return self._select_group_wcdb()

    def _select_group_wcdb(self):
        """使用WCDB方式获取群聊列表"""
        from wechat_decrypt_tool.wcdb_realtime import get_sessions, WCDBRealtimeError

        try:
            sessions = get_sessions(self.handle)
            self.groups = [s for s in sessions if s.get('username', '').endswith('@chatroom')]

            if not self.groups:
                print("  未找到群聊")
                return None

            print("  请选择要监控的群聊:")
            print()

            for i, group in enumerate(self.groups[:30], 1):
                name = group.get('displayName', '') or group.get('username', '')
                name = name[:30] + '...' if len(name) > 30 else name
                print(f"    {i:2d}. {name}")

            if len(self.groups) > 30:
                print(f"\n  ... 还有 {len(self.groups) - 30} 个群聊")

            print()

        except WCDBRealtimeError as e:
            print(f"  获取群聊列表失败: {e}")
            return None

        return self._get_user_choice()

    def _select_group_static(self):
        """使用静态解密方式选择群聊

        优化流程：后台获取群聊列表 → 用户输入关键词搜索 → 选择群聊
        """
        # 后台获取所有群聊（不显示）
        self.groups = self._get_groups_from_session()

        print("  =========== 选择群聊 ===========")
        print()

        if not self.groups:
            print("  未能获取群聊列表，请检查数据库")
            return None

        print(f"  已加载 {len(self.groups)} 个群聊")
        print("  请输入群名称关键词进行搜索")
        print()

        # 直接进入搜索流程
        return self._search_group_interactive()

    def _search_group_interactive(self):
        """交互式群聊搜索

        用户输入关键词 → 显示匹配结果 → 选择编号
        """
        while True:
            try:
                keyword = input("  请输入群名称关键词: ").strip()

                if not keyword:
                    print("  已取消选择")
                    return None

                # 模糊搜索
                matched_groups = self._search_groups_in_contact(keyword)

                if not matched_groups:
                    print(f"  未找到包含 '{keyword}' 的群聊，请重试")
                    print()
                    continue

                # 显示搜索结果
                print()
                print(f"  找到 {len(matched_groups)} 个匹配的群聊:")
                print()

                for i, group in enumerate(matched_groups[:20], 1):
                    name = group.get('displayName', '') or group.get('username', '')
                    # 截断过长的名称
                    if len(name) > 45:
                        name = name[:42] + '...'
                    print(f"    {i:2d}. {name}")

                if len(matched_groups) > 20:
                    print(f"\n  ... 还有 {len(matched_groups) - 20} 个结果")

                print()

                # 选择编号或重新搜索
                while True:
                    try:
                        choice = input("  请输入编号选择，或输入新关键词搜索: ").strip()

                        if not choice:
                            print("  已取消选择")
                            return None

                        # 尝试解析为数字
                        try:
                            idx = int(choice) - 1
                            if 0 <= idx < len(matched_groups):
                                selected = matched_groups[idx]
                                print()
                                print(f"  已选择: {selected.get('displayName', selected.get('username', ''))}")
                                return selected
                            else:
                                print(f"  无效编号，请输入 1-{len(matched_groups)} 之间的数字")
                        except ValueError:
                            # 不是数字，作为新关键词搜索
                            keyword = choice
                            break

                    except (EOFError, KeyboardInterrupt):
                        print()
                        return None

            except (EOFError, KeyboardInterrupt):
                print()
                return None

    def _get_groups_from_session(self) -> list:
        """从 SessionTable 和 contact 表获取群聊列表"""
        import sqlite3

        try:
            # 1. 从 contact 表获取群昵称
            group_names = {}
            if self.decrypted_contact_db and os.path.exists(self.decrypted_contact_db):
                try:
                    conn_contact = sqlite3.connect(self.decrypted_contact_db)
                    cursor_contact = conn_contact.cursor()
                    cursor_contact.execute("""
                        SELECT username, nick_name, remark
                        FROM contact
                        WHERE username LIKE '%@chatroom'
                    """)
                    for row in cursor_contact.fetchall():
                        username, nick_name, remark = row
                        display_name = remark or nick_name or ''
                        if display_name:
                            group_names[username] = display_name
                    conn_contact.close()
                except Exception:
                    pass

            # 2. 从 SessionTable 获取群列表
            conn = sqlite3.connect(self.decrypted_session_db)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT username, last_sender_display_name
                FROM SessionTable
                WHERE username LIKE '%@chatroom'
                ORDER BY sort_timestamp DESC
                LIMIT 200
            """)

            groups = []
            for row in cursor.fetchall():
                username, last_sender_display_name = row
                display_name = group_names.get(username) or last_sender_display_name or username
                groups.append({
                    'username': username,
                    'displayName': display_name
                })

            conn.close()
            return groups

        except Exception as e:
            logger.warning(f"[步骤5] SessionTable查询失败: {e}")
            return []

    def _get_user_choice_with_search(self):
        """获取用户选择，支持搜索功能"""
        while True:
            try:
                choice = input("  请输入编号或's'搜索: ").strip()
                if not choice:
                    return None

                if choice.lower() == 's':
                    return self._search_group_by_name()

                idx = int(choice) - 1
                if 0 <= idx < len(self.groups):
                    return self.groups[idx]
                print("  无效的编号，请重新输入")
            except ValueError:
                print("  请输入数字或's'")
            except (EOFError, KeyboardInterrupt):
                return None

    def _search_group_by_name(self):
        """通过群名称或ID搜索群聊"""
        print("  =========== 群聊搜索 ===========")
        print()
        print("  提示: 输入群名称关键词或群ID")
        print()

        while True:
            try:
                keyword = input("  请输入关键词: ").strip()
                if not keyword:
                    print("  已取消搜索")
                    return None

                matched_groups = self._search_groups_in_contact(keyword)

                if not matched_groups:
                    print(f"  未找到匹配的群聊")
                    print("  请尝试其他关键词，或按 Enter 退出")
                    print()
                    continue

                print()
                print(f"  找到 {len(matched_groups)} 个匹配的群聊:")
                print()

                for i, group in enumerate(matched_groups[:20], 1):
                    name = group.get('displayName', '') or group.get('username', '')
                    name = name[:40] + '...' if len(name) > 40 else name
                    print(f"    {i:2d}. {name}")

                if len(matched_groups) > 20:
                    print(f"\n  ... 还有 {len(matched_groups) - 20} 个结果")

                print()

                while True:
                    try:
                        choice = input("  请输入编号或新关键词: ").strip()
                        if not choice:
                            return None

                        try:
                            idx = int(choice) - 1
                            if 0 <= idx < len(matched_groups):
                                return matched_groups[idx]
                            print("  无效的编号，请重新输入")
                        except ValueError:
                            keyword = choice
                            break
                    except (EOFError, KeyboardInterrupt):
                        return None

            except (EOFError, KeyboardInterrupt):
                return None

    def _search_groups_in_contact(self, keyword: str) -> list:
        """从 contact.db 搜索群聊"""
        import sqlite3

        matched_groups = []

        if self.decrypted_contact_db and os.path.exists(self.decrypted_contact_db):
            try:
                conn = sqlite3.connect(self.decrypted_contact_db)
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT username, nick_name, remark
                    FROM contact
                    WHERE username LIKE '%@chatroom'
                    AND (
                        username LIKE ?
                        OR nick_name LIKE ?
                        OR remark LIKE ?
                    )
                    ORDER BY nick_name
                    LIMIT 100
                """, (f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'))

                rows = cursor.fetchall()
                for row in rows:
                    username, nick_name, remark = row
                    display_name = remark or nick_name or username
                    matched_groups.append({
                        'username': username,
                        'displayName': f"{display_name} ({username})" if display_name != username else username
                    })

                conn.close()

            except Exception as e:
                logger.warning(f"[步骤5] contact.db搜索失败: {e}")

        return matched_groups

    def _get_user_choice(self):
        """获取用户选择的群聊"""
        while True:
            try:
                choice = input("  请输入编号: ").strip()
                if not choice:
                    return None
                idx = int(choice) - 1
                if 0 <= idx < len(self.groups):
                    return self.groups[idx]
                print("  无效的编号，请重新输入")
            except ValueError:
                print("  请输入数字")
            except (EOFError, KeyboardInterrupt):
                return None

    def decode_message(self, raw_content):
        """解码消息内容（处理 zstd 压缩和 hex 字符串）"""
        if raw_content is None:
            return ""

        # 处理 bytes 类型
        if isinstance(raw_content, bytes):
            if raw_content.startswith(ZSTD_MAGIC):
                try:
                    import zstandard as zstd
                    decompressor = zstd.ZstdDecompressor()
                    return decompressor.decompress(raw_content).decode('utf-8', errors='replace')
                except Exception:
                    pass
            return raw_content.decode('utf-8', errors='replace')

        # 处理字符串类型
        text = str(raw_content).strip()

        # 检查是否为 hex 字符串（以 "28b52ffd" 开头的 zstd 压缩数据）
        if len(text) >= 16 and len(text) % 2 == 0:
            try:
                raw = bytes.fromhex(text)
                if raw.startswith(ZSTD_MAGIC):
                    import zstandard as zstd
                    decompressor = zstd.ZstdDecompressor()
                    decompressed = decompressor.decompress(raw)
                    return decompressed.decode('utf-8', errors='replace')
            except Exception:
                pass

        return text

    def start_monitoring(self, target_group):
        """开始监控（参考 monitor_group.py 优化版）"""
        group_id = target_group.get('username', '')
        group_name = target_group.get('displayName', '') or group_id

        if len(group_name) > 25:
            group_name = group_name[:25] + '...'

        print()
        print("=" * 60)
        print(f"  监控: {group_name}")
        print("  按 Ctrl+C 停止")
        print("=" * 60)
        print()

        from wechat_decrypt_tool.message_storage import get_message_storage

        storage = get_message_storage()

        # 轮询配置（参考 monitor_group.py）
        current_interval = POLL_INTERVAL_DEFAULT
        poll_count = 0
        saved_count = 0
        consecutive_no_new = 0

        # 记录已存在的消息时间戳
        last_create_time = 0

        # 获取历史消息
        print("  正在获取历史消息...", flush=True)

        # 优先尝试 WCDB 实时方式获取消息
        messages = []
        if self.handle and self.handle > 0:
            try:
                from wechat_decrypt_tool.wcdb_realtime import get_messages
                messages = get_messages(self.handle, group_id, limit=20)
                if messages:
                    print(f"  [OK] 使用 WCDB 获取到 {len(messages)} 条历史消息")
            except Exception as e:
                logger.warning(f"[监控] WCDB 获取消息失败: {e}")

        # 如果 WCDB 失败，尝试静态解密
        if not messages and getattr(self, 'use_static_mode', False):
            print("  [..] WCDB 方式失败，尝试静态解密...")
            messages = self._get_messages_static(group_id, limit=20)

        if messages:
            # 显示历史消息（最新的5条）
            print(f"  最近 {min(5, len(messages))} 条历史消息:")
            print()

            # 按时间降序显示（最新消息在上）
            display_msgs = messages[:5]
            for msg in display_msgs:
                msg_time = msg.get('create_time') or msg.get('createTime') or 0
                try:
                    msg_time_int = int(msg_time) if msg_time else 0
                except:
                    msg_time_int = 0

                # 获取发送者（使用昵称缓存）
                sender_wxid = msg.get('sender_username') or msg.get('sender') or '未知'
                sender = self._get_display_name(sender_wxid)

                # 解码消息内容
                raw_content = msg.get('message_content') or msg.get('content') or ''
                content = self.decode_message(raw_content)

                # 过滤非纯文字消息（图片、链接等）
                if self._is_non_text_message(content):
                    continue  # 跳过非纯文字消息

                # 清理表情包标记，保留文字
                content = self._clean_message_content(content)

                if len(content.strip()) < 1:
                    continue  # 跳过空消息

                # 显示完整消息内容（不截断）
                content = content[:200] if len(content) > 200 else content

                time_str = datetime.fromtimestamp(msg_time_int).strftime('%H:%M:%S') if msg_time_int else "--:--:--"
                print(f"    [{time_str}] {sender}: {content}")

            print()

            # 更新最新消息时间戳
            for msg in messages:
                msg_time = msg.get('create_time') or msg.get('createTime') or 0
                try:
                    msg_time_int = int(msg_time) if msg_time else 0
                except:
                    msg_time_int = 0
                if msg_time_int > last_create_time:
                    last_create_time = msg_time_int

            time_str = datetime.fromtimestamp(last_create_time).strftime('%Y-%m-%d %H:%M:%S') if last_create_time else "无"
            print(f"  当前最新消息时间: {time_str}")

        print(f"  自适应轮询: 最小 {POLL_INTERVAL_MIN} 秒, 最大 {POLL_INTERVAL_MAX} 秒")
        print()

        # 开始监控循环
        try:
            while True:
                # 等待
                time.sleep(current_interval)
                poll_count += 1

                # 获取最新消息
                try:
                    # 优先使用 WCDB 实时方式
                    if self.handle and self.handle > 0:
                        from wechat_decrypt_tool.wcdb_realtime import get_messages
                        new_messages = get_messages(self.handle, group_id, limit=10)
                    elif getattr(self, 'use_static_mode', False):
                        new_messages = self._get_messages_static(group_id, limit=10)
                    else:
                        new_messages = []
                except Exception as e:
                    logger.warning(f"[监控] 获取消息失败: {e}")
                    continue

                # 找到最新的时间戳
                max_time_in_batch = 0
                for msg in new_messages:
                    msg_time = msg.get('create_time') or msg.get('createTime') or 0
                    try:
                        msg_time_int = int(msg_time) if msg_time else 0
                    except:
                        msg_time_int = 0
                    if msg_time_int > max_time_in_batch:
                        max_time_in_batch = msg_time_int

                # 调试：显示轮询状态（每30次）
                if poll_count % 30 == 0:
                    time_str = datetime.fromtimestamp(max_time_in_batch).strftime('%H:%M:%S') if max_time_in_batch else "无"
                    logger.debug(f"[轮询 {poll_count}] 间隔: {current_interval:.1f}s, 消息数: {len(new_messages)}, 最新: {time_str}")

                # 如果有新消息
                if max_time_in_batch > last_create_time:
                    # 更新时间戳
                    old_last_time = last_create_time
                    last_create_time = max_time_in_batch

                    # 重置连续无新消息计数
                    consecutive_no_new = 0

                    # 自适应：有新消息时，加快轮询
                    current_interval = max(POLL_INTERVAL_MIN, current_interval * 0.5)

                    # 输出所有新消息（降序排列，最新在上）
                    time_str = datetime.fromtimestamp(max_time_in_batch).strftime('%Y-%m-%d %H:%M:%S')
                    print(f"\n[新消息] {time_str}", flush=True)

                    # 反转消息列表，使最新消息在上
                    for msg in reversed(new_messages):
                        msg_time = msg.get('create_time') or msg.get('createTime') or 0
                        try:
                            msg_time_int = int(msg_time) if msg_time else 0
                        except:
                            msg_time_int = 0

                        # 只输出时间戳大于旧记录的消息
                        if msg_time_int > old_last_time:
                            # 获取发送者（使用昵称缓存）
                            sender_wxid = msg.get('sender_username') or msg.get('sender') or '未知'
                            sender = self._get_display_name(sender_wxid)
                            content = self.decode_message(msg.get('message_content') or msg.get('content') or '')

                            # 过滤非纯文字消息
                            if self._is_non_text_message(content):
                                continue

                            # 清理表情包标记，保留文字
                            content = self._clean_message_content(content)

                            if len(content.strip()) < 1:
                                continue

                            time_str = datetime.fromtimestamp(msg_time_int).strftime('%H:%M:%S')
                            # 显示完整消息内容（不截断）
                            content_preview = content[:200] if len(content) > 200 else content
                            print(f"  [{time_str}] {sender}: {content_preview}", flush=True)

                            # 保存到数据库
                            try:
                                storage.save_message(
                                    sender_nickname=sender,
                                    message_content=content,
                                    send_time=datetime.fromtimestamp(msg_time_int),
                                    group_name=group_name,
                                    group_id=group_id,
                                    sender_id=sender_wxid
                                )
                                saved_count += 1
                            except Exception as e:
                                logger.warning(f"[监控] 保存消息失败: {e}")
                else:
                    # 无新消息
                    consecutive_no_new += 1

                    # 自适应：无新消息时，逐渐放慢轮询
                    current_interval = min(POLL_INTERVAL_MAX, current_interval * 1.5)

        except KeyboardInterrupt:
            print('\n\n[监听已停止]')
            print(f'[统计] 轮询次数: {poll_count}, 最终间隔: {current_interval:.1f}秒')
            if saved_count > 0:
                print(f'[已保存 {saved_count} 条消息到数据库]')

    def _get_messages_static(self, group_id: str, limit: int = 30) -> list:
        """使用静态解密方式获取消息

        消息存储在 message/*.db 文件的 Msg_<MD5(group_id)> 表中
        参考 chat_realtime_reader.py 的实现
        """
        import sqlite3
        import hashlib
        from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor
        from wechat_decrypt_tool.constants import ZSTD_MAGIC

        logger.info(f"[消息查询] 开始查询群聊消息, group_id={group_id}, limit={limit}")

        if not self.db_key or not self.temp_dir:
            logger.warning("[消息查询] 密钥或临时目录未初始化")
            return []

        # 计算消息表名: Msg_<MD5(group_id)>
        expected_table = f"Msg_{hashlib.md5(group_id.encode('utf-8')).hexdigest()}"
        logger.debug(f"[消息查询] 期望表名: {expected_table}")

        # 查找 message 目录
        session_db_path = self._find_session_db()
        if not session_db_path:
            logger.warning("[消息查询] session.db 路径未找到")
            return []

        # 获取 db_storage 目录
        db_storage_dir = os.path.dirname(os.path.dirname(session_db_path))
        message_dir = os.path.join(db_storage_dir, "message")

        if not os.path.exists(message_dir):
            logger.warning(f"[消息查询] 消息目录不存在: {message_dir}")
            return []

        # 获取所有消息数据库文件
        message_dbs = []
        for f in os.listdir(message_dir):
            if f.endswith(".db") and not f.endswith("-shm") and not f.endswith("-wal"):
                if "message" in f.lower():
                    message_dbs.append(f)

        # 排序：普通消息优先，biz 次之
        message_dbs.sort(key=lambda x: (0 if x.startswith("message_") else 1, x))

        logger.debug(f"[消息查询] 找到 {len(message_dbs)} 个消息数据库")

        decryptor = WeChatDatabaseDecryptor(self.db_key)
        messages = []

        # 遍历数据库查找目标表
        for db_name in message_dbs[:5]:  # 只检查前5个数据库
            db_path = os.path.join(message_dir, db_name)
            temp_db = os.path.join(self.temp_dir, f"temp_{db_name}")

            try:
                # 解密数据库
                if not decryptor.decrypt_database(db_path, temp_db):
                    continue

                conn = sqlite3.connect(temp_db)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # 查找目标表（大小写不敏感）
                cursor.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND lower(name)=lower(?)
                    LIMIT 1
                """, (expected_table,))

                row = cursor.fetchone()
                if not row:
                    conn.close()
                    continue

                actual_table = row[0]
                logger.debug(f"[消息查询] 在 {db_name} 中找到表: {actual_table}")

                # 检查表字段
                cursor.execute(f"PRAGMA table_info({actual_table})")
                columns = [col[1] for col in cursor.fetchall()]

                # 查询消息
                # 根据字段选择查询语句
                if 'compress_content' in columns:
                    cursor.execute(f"""
                        SELECT local_id, create_time, message_content, compress_content, real_sender_id
                        FROM {actual_table}
                        ORDER BY create_time DESC
                        LIMIT ?
                    """, (limit,))
                else:
                    cursor.execute(f"""
                        SELECT local_id, create_time, message_content, real_sender_id
                        FROM {actual_table}
                        ORDER BY create_time DESC
                        LIMIT ?
                    """, (limit,))

                rows = cursor.fetchall()
                logger.debug(f"[消息查询] 查询到 {len(rows)} 条消息")

                for row in rows:
                    try:
                        # 解码消息内容
                        content = row['message_content']
                        compress = row['compress_content'] if 'compress_content' in row.keys() else None

                        # 优先使用 compress_content
                        if compress and isinstance(compress, bytes):
                            try:
                                if compress.startswith(ZSTD_MAGIC):
                                    import zstandard as zstd
                                    decompressor = zstd.ZstdDecompressor()
                                    content = decompressor.decompress(compress).decode('utf-8')
                                else:
                                    content = compress.decode('utf-8', errors='replace')
                            except Exception:
                                pass
                        elif isinstance(content, bytes):
                            try:
                                if content.startswith(ZSTD_MAGIC):
                                    import zstandard as zstd
                                    decompressor = zstd.ZstdDecompressor()
                                    content = decompressor.decompress(content).decode('utf-8')
                                else:
                                    content = content.decode('utf-8', errors='replace')
                            except Exception:
                                content = str(content)

                        # 获取发送者
                        sender_wxid = row['real_sender_id'] if row['real_sender_id'] else '未知'

                        messages.append({
                            'local_id': row['local_id'],
                            'create_time': row['create_time'] or 0,
                            'message_content': content or '',
                            'sender_username': sender_wxid
                        })
                    except Exception as e:
                        logger.warning(f"[消息查询] 解析消息失败: {e}")
                        continue

                conn.close()

                # 找到消息后就退出
                if messages:
                    break

            except Exception as e:
                logger.warning(f"[消息查询] 处理 {db_name} 失败: {e}")
                continue
            finally:
                # 清理临时文件
                try:
                    if os.path.exists(temp_db):
                        os.remove(temp_db)
                except Exception:
                    pass

        return messages

    def run(self):
        """运行主流程"""
        self.print_header()

        if not self.step1_detect_process():
            self._wait_exit()
            return

        if not self.step2_detect_account():
            self._wait_exit()
            return

        if not self.step3_get_key():
            self._wait_exit()
            return

        if not self.step4_connect_db():
            self._wait_exit()
            return

        target_group = self.step5_select_group()
        if not target_group:
            print()
            print("  已取消")
            return

        self.start_monitoring(target_group)

    def _wait_exit(self):
        """等待退出"""
        print()
        input("  按 Enter 键退出...")


def main():
    """主函数"""
    try:
        monitor = SimpleMonitor()
        monitor.run()
    except Exception as e:
        logger.exception(f"程序异常: {e}")
        print(f"\n  程序异常: {e}")
        input("  按 Enter 键退出...")
        sys.exit(1)


if __name__ == '__main__':
    main()
