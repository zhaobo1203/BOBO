#!/usr/bin/env python3
"""
微信群消息监听系统 - 主程序入口 (tn_combined_v3)

按照 TECHNICAL_SPECIFICATION_REPORT.md 规格实现的完整流程编排。
支持 TN-01 ~ TN-06 全部技术节点的自动化处理。

功能模块:
- TN-01: 微信进程检测与管理
- TN-02: 当前登录账号检测
- TN-03: 密钥获取（内存扫描/已保存密钥）
- TN-04: 数据库解密
- TN-05: WCDB实时消息监听
- TN-06: 消息持久化存储

使用方法:
    python tn_combined_v3.py                    # 交互式选择群聊
    python tn_combined_v3.py --list             # 列出所有群聊
    python tn_combined_v3.py -g "群名称"        # 监控指定群聊
    python tn_combined_v3.py -g "群名称" -d     # 导出历史消息
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from wechat_decrypt_tool.constants import ErrorCode, POLL_INTERVAL_DEFAULT, POLL_INTERVAL_MIN, POLL_INTERVAL_MAX
from wechat_decrypt_tool.logging_config import get_logger, setup_logging

logger = get_logger(__name__)


class WeChatMonitor:
    """微信群消息监听主控制器
    
    按技术规格报告实现完整的初始化和监听流程。
    支持WCDB实时模式和静态解密模式。
    """
    
    def __init__(self):
        """初始化监听器"""
        self.pid: Optional[int] = None
        self.account_id: Optional[str] = None
        self.data_path: Optional[str] = None
        self.db_key: Optional[str] = None
        self.handle: Optional[int] = None
        self.groups: List[Dict[str, Any]] = []
        # 静态解密模式相关
        self.use_static_mode: bool = False
        self.temp_dir: Optional[str] = None
        self.decrypted_session_db: Optional[str] = None
        self.decrypted_contact_db: Optional[str] = None
        
    def step1_detect_wechat_process(self) -> bool:
        """
        TN-01: 检测微信进程
        
        Returns:
            bool: 是否检测到微信进程
        """
        logger.info("[TN-01] 开始检测微信进程...")
        
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
            logger.info(f"[TN-01] 检测到微信进程: PID={self.pid}, 进程数={len(wechat_processes)}")
            return True
        else:
            logger.warning(f"[TN-01] {ErrorCode.ERR_PROC_001}")
            return False
    
    def step2_detect_account(self) -> bool:
        """
        TN-02: 检测当前登录账号
        
        Returns:
            bool: 是否成功检测到账号
        """
        logger.info("[TN-02] 开始检测当前登录账号...")
        
        from wechat_decrypt_tool.wechat_detection import detect_current_logged_in_account, auto_detect_wechat_data_dirs
        
        # 检测数据目录
        detected_dirs = auto_detect_wechat_data_dirs()
        if not detected_dirs:
            logger.error(f"[TN-02] {ErrorCode.ERR_ACCOUNT_003}")
            return False
        
        # 检测当前登录账号
        result = detect_current_logged_in_account()
        
        if result.get('current_account'):
            self.account_id = result['current_account']
            self.data_path = detected_dirs[0]
            logger.info(f"[TN-02] 检测到当前账号: {self.account_id}")
            logger.info(f"[TN-02] 数据目录: {self.data_path}")
            return True
        else:
            logger.warning(f"[TN-02] 未检测到当前登录账号")
            # 使用第一个检测到的目录作为备用
            self.data_path = detected_dirs[0]
            return True
    
    def step3_get_key(self) -> bool:
        """
        TN-03: 获取数据库密钥
        
        优先级:
        1. Hook注入获取 (优先，快速可靠)
        2. 已保存的密钥 (托底)
        
        Returns:
            bool: 是否成功获取密钥
        """
        logger.info("[TN-03] 开始获取数据库密钥...")
        
        # 方法1: Hook注入获取 (优先方案)
        if self.pid:
            logger.info("[TN-03] 尝试Hook注入获取密钥...")
            try:
                import wx_key
                
                # 初始化Hook - 需要传入目标进程PID
                if wx_key.initialize_hook(self.pid):
                    logger.info("[TN-03] Hook初始化成功，等待获取密钥...")
                    
                    # 轮询获取密钥数据
                    for i in range(30):  # 最多等待30秒
                        time.sleep(1)
                        key_data = wx_key.poll_key_data()
                        
                        if key_data and isinstance(key_data, dict):
                            # 提取密钥
                            db_key = key_data.get('key') or key_data.get('db_key')
                            if db_key and len(db_key) == 64:
                                self.db_key = db_key
                                logger.info("[TN-03] Hook注入成功获取密钥")
                                wx_key.cleanup_hook()
                                # 保存密钥
                                self._save_key()
                                return True
                        
                        if i % 5 == 4:
                            logger.info(f"[TN-03] 等待密钥... ({i+1}秒)")
                    
                    logger.warning("[TN-03] Hook等待超时")
                    wx_key.cleanup_hook()
                else:
                    error_msg = wx_key.get_last_error_msg() or "未知错误"
                    logger.warning(f"[TN-03] Hook初始化失败: {error_msg}")
                    
            except ImportError:
                logger.warning(f"[TN-03] {ErrorCode.ERR_KEY_005}")
            except Exception as e:
                logger.warning(f"[TN-03] Hook注入失败: {e}")
        
        # 方法2: 从已保存文件加载 (托底方案)
        logger.info("[TN-03] 尝试加载已保存密钥...")
        from wechat_decrypt_tool.key_store import load_account_keys_store
        
        store = load_account_keys_store()
        
        if store and 'accounts' in store:
            # 尝试通过账号ID匹配
            for account_id, account_data in store.get('accounts', {}).items():
                if account_id == self.account_id or (self.account_id and account_id.startswith(self.account_id.split('_')[0] + '_' + self.account_id.split('_')[1] if '_' in self.account_id else self.account_id)):
                    key = account_data.get('db_key')
                    if key and len(key) == 64:
                        self.db_key = key
                        logger.info(f"[TN-03] 使用已保存密钥: 账号={account_id}")
                        return True
            
            # 尝试通过data_path匹配
            for account_data in store.get('accounts', {}).values():
                stored_path = account_data.get('data_path', '')
                if stored_path and self.data_path:
                    # 规范化路径比较
                    normalized_stored = os.path.normpath(stored_path).lower()
                    normalized_current = os.path.normpath(self.data_path).lower()
                    if normalized_stored in normalized_current or normalized_current in normalized_stored:
                        key = account_data.get('db_key')
                        if key and len(key) == 64:
                            self.db_key = key
                            logger.info(f"[TN-03] 通过路径匹配到密钥")
                            return True
        
        logger.error(f"[TN-03] {ErrorCode.ERR_KEY_002}")
        return False
    
    def _save_key(self) -> None:
        """保存密钥到存储"""
        from wechat_decrypt_tool.key_store import upsert_account_keys_in_store
        
        if self.account_id and self.db_key:
            upsert_account_keys_in_store(
                self.account_id,
                db_key=self.db_key,
                db_key_source_wxid_dir=self.data_path
            )
            logger.info(f"[TN-03] 密钥已保存到存储")
    
    def step4_decrypt_databases(self, output_dir: Optional[str] = None) -> bool:
        """
        TN-04: 解密数据库
        
        Args:
            output_dir: 输出目录，默认为 output/databases
        
        Returns:
            bool: 是否成功解密
        """
        logger.info("[TN-04] 开始解密数据库...")
        
        if not self.db_key:
            logger.error(f"[TN-04] {ErrorCode.ERR_DECRYPT_001}")
            return False
        
        from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor, scan_account_databases_from_path
        from wechat_decrypt_tool.app_paths import get_output_databases_dir
        
        # 确定输出目录
        if not output_dir:
            output_dir = str(get_output_databases_dir())
        
        # 扫描数据库
        db_storage_path = Path(self.data_path) / 'db_storage' if self.data_path else None
        if not db_storage_path or not db_storage_path.exists():
            logger.error(f"[TN-04] {ErrorCode.ERR_DECRYPT_002}")
            return False
        
        scan_result = scan_account_databases_from_path(str(db_storage_path))
        if scan_result.get('status') != 'success':
            logger.error(f"[TN-04] 扫描数据库失败: {scan_result.get('message')}")
            return False
        
        # 解密数据库
        decryptor = WeChatDatabaseDecryptor(self.db_key)
        databases = scan_result.get('account_databases', {}).get(self.account_id or 'unknown', [])
        
        success_count = 0
        for db_info in databases[:10]:  # 只解密关键数据库
            db_path = db_info['path']
            db_name = db_info['name']
            output_path = str(Path(output_dir) / db_name)
            
            try:
                if decryptor.decrypt_database(db_path, output_path):
                    success_count += 1
                    logger.info(f"[TN-04] 解密成功: {db_name}")
            except Exception as e:
                logger.warning(f"[TN-04] 解密失败: {db_name}, 错误: {e}")
        
        logger.info(f"[TN-04] 解密完成: 成功 {success_count}/{len(databases[:10])}")
        return success_count > 0
    
    def step5_open_wcdb(self) -> bool:
        """
        TN-05: 打开WCDB实时连接或静态解密连接
        
        优先尝试WCDB实时连接，失败则回退到静态解密模式。
        
        Returns:
            bool: 是否成功打开连接
        """
        logger.info("[TN-05] 开始连接数据库...")
        
        if not self.db_key:
            logger.error(f"[TN-05] {ErrorCode.ERR_WCDB_002}")
            return False
        
        # 查找session.db路径
        session_db_path = self._find_session_db()
        if not session_db_path:
            logger.error(f"[TN-05] {ErrorCode.ERR_WCDB_001}")
            return False
        
        # 方法1: 尝试WCDB实时连接
        logger.info("[TN-05] 尝试WCDB实时连接...")
        try:
            from wechat_decrypt_tool.wcdb_realtime import open_account, WCDBRealtimeError
            import concurrent.futures
            
            def _connect():
                return open_account(session_db_path, self.db_key, self.account_id or '')
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_connect)
                try:
                    self.handle = future.result(timeout=15)
                except concurrent.futures.TimeoutError:
                    logger.warning("[TN-05] WCDB连接超时(15秒)，切换到静态解密模式")
                    self.handle = None
            
            if self.handle and self.handle > 0:
                logger.info(f"[TN-05] WCDB连接成功, handle={self.handle}")
                self.use_static_mode = False
                return True
        except WCDBRealtimeError as e:
            logger.warning(f"[TN-05] WCDB连接失败: {e}，切换到静态解密模式")
            self.handle = None
        except Exception as e:
            logger.warning(f"[TN-05] WCDB连接异常: {e}，切换到静态解密模式")
            self.handle = None
        
        # 方法2: 回退到静态解密模式
        logger.info("[TN-05] 使用静态解密模式...")
        if self._connect_via_static_decrypt(session_db_path):
            self.use_static_mode = True
            logger.info("[TN-05] 静态解密连接成功")
            return True
        
        logger.error("[TN-05] 所有连接方式均失败")
        return False
    
    def _connect_via_static_decrypt(self, session_db_path: str) -> bool:
        """通过静态解密方式连接数据库"""
        import tempfile
        import sqlite3
        from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor
        
        self.temp_dir = tempfile.mkdtemp(prefix="wechat_monitor_")
        
        decryptor = WeChatDatabaseDecryptor(self.db_key)
        self.decrypted_session_db = os.path.join(self.temp_dir, "session.db")
        
        if not decryptor.decrypt_database(session_db_path, self.decrypted_session_db):
            logger.error("[TN-05] session.db 解密失败")
            return False
        
        logger.info("[TN-05] session.db 解密成功")
        
        # 尝试解密contact.db
        contact_db_path = self._find_contact_db()
        if contact_db_path:
            self.decrypted_contact_db = os.path.join(self.temp_dir, "contact.db")
            if decryptor.decrypt_database(contact_db_path, self.decrypted_contact_db):
                logger.info("[TN-05] contact.db 解密成功")
            else:
                self.decrypted_contact_db = None
        else:
            self.decrypted_contact_db = None
        
        # 验证解密后的数据库
        try:
            conn = sqlite3.connect(self.decrypted_session_db)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
            cursor.fetchone()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"[TN-05] 数据库验证失败: {e}")
            return False
    
    def _find_contact_db(self) -> Optional[str]:
        """查找contact.db文件路径"""
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
    
    def _find_session_db(self) -> Optional[str]:
        """查找session.db文件路径"""
        if not self.data_path:
            return None
        
        session_paths = [
            Path(self.data_path) / 'db_storage' / 'session' / 'session.db',
            Path(self.data_path) / 'db_storage' / 'session.db',
            Path(self.data_path) / 'session.db',
        ]
        
        # 动态搜索wxid开头的子目录
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
                logger.info(f"[TN-05] 找到session.db: {path}")
                return str(path)
        
        logger.error("[TN-05] 未找到session.db")
        return None
    
    def step6_load_groups(self) -> List[Dict[str, Any]]:
        """
        TN-05: 加载群聊列表
        
        支持WCDB模式和静态解密模式。
        
        Returns:
            群聊列表
        """
        logger.info("[TN-05] 加载群聊列表...")
        
        if self.use_static_mode:
            return self._load_groups_static()
        else:
            return self._load_groups_wcdb()
    
    def _load_groups_wcdb(self) -> List[Dict[str, Any]]:
        """使用WCDB模式加载群聊列表"""
        if not self.handle:
            logger.error("[TN-05] WCDB未连接")
            return []
        
        from wechat_decrypt_tool.wcdb_realtime import get_sessions, WCDBRealtimeError
        
        try:
            sessions = get_sessions(self.handle)
            # 过滤群聊 (以 @chatroom 结尾)
            self.groups = [
                s for s in sessions
                if s.get('username', '').endswith('@chatroom')
            ]
            logger.info(f"[TN-05] WCDB模式加载到 {len(self.groups)} 个群聊")
            return self.groups
        except WCDBRealtimeError as e:
            logger.error(f"[TN-05] 加载群聊失败: {e}")
            return []
    
    def _load_groups_static(self) -> List[Dict[str, Any]]:
        """使用静态解密模式加载群聊列表"""
        import sqlite3
        
        if not self.decrypted_session_db or not os.path.exists(self.decrypted_session_db):
            logger.error("[TN-05] 静态模式: session.db未解密")
            return []
        
        try:
            # 从contact表获取群昵称
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
                except Exception as e:
                    logger.warning(f"[TN-05] contact表查询失败: {e}")
            
            # 从SessionTable获取群列表
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
            self.groups = groups
            logger.info(f"[TN-05] 静态模式加载到 {len(groups)} 个群聊")
            return groups
            
        except Exception as e:
            logger.error(f"[TN-05] 静态模式加载群聊失败: {e}")
            return []
    
    def monitor_group(self, group_id: str, group_name: str = '', interval: float = POLL_INTERVAL_DEFAULT) -> None:
        """
        TN-05/TN-06: 监控指定群聊
        
        支持WCDB模式和静态解密模式。
        
        Args:
            group_id: 群ID
            group_name: 群名称
            interval: 轮询间隔（秒）
        """
        logger.info(f"[监控] 开始监控群聊: {group_name or group_id}")
        
        if self.use_static_mode:
            self._monitor_group_static(group_id, group_name, interval)
        else:
            self._monitor_group_wcdb(group_id, group_name, interval)
    
    def _monitor_group_wcdb(self, group_id: str, group_name: str, interval: float) -> None:
        """使用WCDB模式监控群聊"""
        if not self.handle:
            logger.error("[监控] WCDB未连接")
            print("[错误] 数据库未连接")
            return
        
        from wechat_decrypt_tool.wcdb_realtime import get_messages, WCDBRealtimeError
        from wechat_decrypt_tool.message_storage import get_message_storage
        
        storage = get_message_storage()
        last_time = 0
        current_interval = interval
        msg_count = 0
        
        print(f"\n{'='*60}")
        print(f"  监控群聊: {group_name or group_id}")
        print(f"  群ID: {group_id}")
        print(f"  模式: WCDB实时")
        print(f"  按 Ctrl+C 停止监控")
        print(f"{'='*60}\n")
        
        try:
            while True:
                time.sleep(current_interval)
                
                try:
                    messages = get_messages(self.handle, group_id, limit=30)
                    new_messages = [m for m in messages if m.get('create_time', 0) > last_time]
                    
                    if new_messages:
                        current_interval = max(POLL_INTERVAL_MIN, current_interval * 0.8)
                        
                        for msg in new_messages:
                            last_time = msg.get('create_time', 0)
                            content = self._decode_message_content(msg.get('message_content', ''))
                            sender = msg.get('sender_username', '未知')
                            
                            # 过滤非文字消息
                            if content.startswith('<'):
                                continue
                            
                            send_time = datetime.fromtimestamp(last_time).strftime('%H:%M:%S')
                            print(f"  [{send_time}] {sender[:10]}: {content[:60]}")
                            msg_count += 1
                            
                            storage.save_message(
                                sender_nickname=sender,
                                message_content=content,
                                send_time=datetime.fromtimestamp(last_time),
                                group_name=group_name,
                                group_id=group_id
                            )
                    else:
                        current_interval = min(POLL_INTERVAL_MAX, current_interval * 1.1)
                        
                except WCDBRealtimeError as e:
                    logger.error(f"[监控] WCDB错误: {e}")
                    time.sleep(5)
                    
        except KeyboardInterrupt:
            print(f"\n\n  监控已停止，共捕获 {msg_count} 条消息\n")
    
    def _monitor_group_static(self, group_id: str, group_name: str, interval: float) -> None:
        """使用静态解密模式监控群聊"""
        import sqlite3
        from wechat_decrypt_tool.message_storage import get_message_storage
        from wechat_decrypt_tool.constants import ZSTD_MAGIC
        from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor
        
        storage = get_message_storage()
        last_time = 0
        current_interval = interval
        msg_count = 0
        
        print(f"\n{'='*60}")
        print(f"  监控群聊: {group_name or group_id}")
        print(f"  群ID: {group_id}")
        print(f"  模式: 静态解密")
        print(f"  按 Ctrl+C 停止监控")
        print(f"{'='*60}\n")
        
        session_db_path = self._find_session_db()
        if not session_db_path:
            print("[错误] 无法找到session.db")
            return
        
        try:
            while True:
                time.sleep(current_interval)
                
                try:
                    # 每次重新解密获取最新消息
                    messages = self._get_messages_static(group_id, session_db_path, limit=30)
                    new_messages = [m for m in messages if m.get('create_time', 0) > last_time]
                    
                    if new_messages:
                        current_interval = max(POLL_INTERVAL_MIN, current_interval * 0.8)
                        logger.info(f"[监控] 检测到 {len(new_messages)} 条新消息")
                        
                        for msg in new_messages:
                            last_time = msg.get('create_time', 0)
                            content = msg.get('message_content', '')
                            
                            # 过滤非文字消息
                            if content.startswith('<'):
                                continue
                            
                            sender = msg.get('sender_username', '未知')
                            if len(sender) > 10:
                                sender = sender[:10] + '...'
                            
                            send_time = datetime.fromtimestamp(last_time).strftime('%H:%M:%S')
                            print(f"  [{send_time}] {sender}: {content[:60]}")
                            if len(content) > 60:
                                print(f"      {content[60:120]}")
                            
                            msg_count += 1
                            
                            storage.save_message(
                                sender_nickname=sender,
                                message_content=content,
                                send_time=datetime.fromtimestamp(last_time),
                                group_name=group_name,
                                group_id=group_id
                            )
                    else:
                        current_interval = min(POLL_INTERVAL_MAX, current_interval * 1.1)
                        
                except Exception as e:
                    logger.error(f"[监控] 消息查询异常: {e}")
                    time.sleep(5)
                    
        except KeyboardInterrupt:
            print(f"\n\n  监控已停止，共捕获 {msg_count} 条消息\n")
    
    def _get_messages_static(self, group_id: str, session_db_path: str, limit: int = 30) -> List[Dict[str, Any]]:
        """使用静态解密方式获取消息"""
        import sqlite3
        from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor
        
        if not self.db_key or not self.temp_dir:
            return []
        
        # 每次重新解密session.db获取最新消息
        temp_session = os.path.join(self.temp_dir, "session_latest.db")
        
        try:
            decryptor = WeChatDatabaseDecryptor(self.db_key)
            if not decryptor.decrypt_database(session_db_path, temp_session):
                return []
        except Exception as e:
            logger.error(f"[消息查询] 解密失败: {e}")
            return []
        
        try:
            conn = sqlite3.connect(temp_session)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 检查表结构
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            # 确定消息表名
            table_name = 'session'
            if 'Session' in tables and 'session' not in tables:
                table_name = 'Session'
            
            if table_name not in tables:
                conn.close()
                return []
            
            # 查询群消息
            cursor.execute(f"""
                SELECT localId, create_time, message_content, sender_username, session_username
                FROM {table_name}
                WHERE session_username = ?
                ORDER BY create_time DESC
                LIMIT ?
            """, (group_id, limit))
            
            rows = cursor.fetchall()
            messages = []
            
            for row in rows:
                try:
                    content = row['message_content']
                    # 处理 zstd 压缩
                    if isinstance(content, bytes):
                        try:
                            if content.startswith(ZSTD_MAGIC):
                                import zstandard as zstd
                                decompressor = zstd.ZstdDecompressor()
                                content = decompressor.decompress(content).decode('utf-8')
                            else:
                                content = content.decode('utf-8', errors='replace')
                        except Exception:
                            content = str(content)
                    
                    messages.append({
                        'local_id': row['localId'],
                        'create_time': row['create_time'] or 0,
                        'message_content': content or '',
                        'sender_username': row['sender_username'] or '未知'
                    })
                except Exception as e:
                    logger.warning(f"[消息查询] 解析消息失败: {e}")
                    continue
            
            conn.close()
            return messages
            
        except Exception as e:
            logger.error(f"[消息查询] 查询异常: {e}")
            return []
        finally:
            try:
                os.remove(temp_session)
            except Exception:
                pass
    
    def _decode_message_content(self, raw_content) -> str:
        """解码消息内容（处理zstd压缩）"""
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
    
    def run_full_flow(self) -> bool:
        """
        执行完整初始化流程
        
        Returns:
            bool: 是否成功初始化
        """
        print("\n" + "="*60)
        print("  WeChat Group Monitor - 初始化流程")
        print("="*60 + "\n")
        
        # TN-01: 检测微信进程
        if not self.step1_detect_wechat_process():
            print(f"\n[错误] {ErrorCode.ERR_PROC_001}")
            print("请先启动微信客户端并登录")
            return False
        
        # TN-02: 检测账号
        if not self.step2_detect_account():
            print(f"\n[错误] 账号检测失败")
            return False
        
        # TN-03: 获取密钥
        if not self.step3_get_key():
            print(f"\n[错误] {ErrorCode.ERR_KEY_002}")
            return False
        
        # TN-05: 打开WCDB连接
        if not self.step5_open_wcdb():
            print(f"\n[错误] WCDB连接失败")
            return False
        
        # TN-05: 加载群聊列表
        groups = self.step6_load_groups()
        if not groups:
            print("\n[警告] 未检测到群聊")
        
        print("\n" + "-"*60)
        print(f"  账号: {self.account_id}")
        print(f"  密钥: {self.db_key[:16]}..." if self.db_key else "  密钥: 未获取")
        print(f"  群聊数: {len(groups)}")
        print("-"*60 + "\n")
        
        return True
    
    def interactive_select_group(self) -> Optional[Dict[str, Any]]:
        """
        交互式选择群聊
        
        Returns:
            选中的群聊信息
        """
        if not self.groups:
            print("没有可用的群聊")
            return None
        
        print("\n请选择要监控的群聊:\n")
        for i, group in enumerate(self.groups[:30], 1):
            name = group.get('displayName', '') or group.get('username', '')
            print(f"  {i:2d}. {name[:30]}")
        
        if len(self.groups) > 30:
            print(f"\n  ... 还有 {len(self.groups) - 30} 个群聊")
        
        print()
        try:
            choice = int(input("请输入群聊编号 (0退出): "))
            if choice == 0:
                return None
            if 1 <= choice <= len(self.groups):
                return self.groups[choice - 1]
        except (ValueError, EOFError):
            pass
        
        return None


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='微信群消息监听系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python tn_combined_v3.py                    # 交互式选择群聊
    python tn_combined_v3.py --list             # 列出所有群聊
    python tn_combined_v3.py -g "群名称"        # 监控指定群聊
    python tn_combined_v3.py -g "群名称" -d     # 导出历史消息
        """
    )
    
    parser.add_argument('-g', '--group', type=str, help='要监控的群名称')
    parser.add_argument('-i', '--interval', type=float, default=POLL_INTERVAL_DEFAULT, help='轮询间隔（秒）')
    parser.add_argument('--list', action='store_true', help='列出所有群聊')
    parser.add_argument('-d', '--decrypt', action='store_true', help='解密数据库')
    parser.add_argument('--debug', action='store_true', help='调试模式')
    
    args = parser.parse_args()
    
    # 设置日志
    setup_logging()
    
    if args.debug:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)
    
    # 创建监控器
    monitor = WeChatMonitor()
    
    # 执行初始化流程
    if not monitor.run_full_flow():
        sys.exit(1)
    
    # 列出群聊
    if args.list:
        print("\n群聊列表:\n")
        for i, group in enumerate(monitor.groups, 1):
            name = group.get('displayName', '') or group.get('username', '')
            print(f"  {i:3d}. {name}")
        print(f"\n共 {len(monitor.groups)} 个群聊")
        sys.exit(0)
    
    # 解密数据库
    if args.decrypt:
        monitor.step4_decrypt_databases()
        sys.exit(0)
    
    # 选择或查找群聊
    target_group = None
    if args.group:
        # 查找匹配的群聊
        for group in monitor.groups:
            name = group.get('displayName', '') or group.get('username', '')
            if args.group.lower() in name.lower():
                target_group = group
                break
        
        if not target_group:
            print(f"\n[错误] 未找到群聊: {args.group}")
            sys.exit(1)
    else:
        # 交互式选择
        target_group = monitor.interactive_select_group()
    
    # 开始监控
    if target_group:
        group_id = target_group.get('username', '')
        group_name = target_group.get('displayName', '') or group_id
        monitor.monitor_group(group_id, group_name, args.interval)
    
    sys.exit(0)


if __name__ == '__main__':
    main()