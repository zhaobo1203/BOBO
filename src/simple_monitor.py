#!/usr/bin/env python3
"""
微信群消息监听系统 - 简化版一键启动

流程: 启动 → 进程检测 → 账号识别 → 密钥获取 → 数据库解密 → 选择群聊 → 实时监控
"""

import sys
import os
import time
import logging
import multiprocessing
import sqlite3
import tempfile
import hashlib
import json
import re
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional, Any, List, Dict

# Windows PyInstaller 打包必须：防止 multiprocessing 子进程重新执行主程序
# 必须在程序最开始时调用，否则会导致程序卡死
multiprocessing.freeze_support()

# 添加项目路径
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).parent))

from wechat_decrypt_tool.exe_logging import setup_exe_logging, get_exe_logger, get_exe_dir
from wechat_decrypt_tool.constants import POLL_INTERVAL_DEFAULT, POLL_INTERVAL_MIN, POLL_INTERVAL_MAX, ZSTD_MAGIC
from wechat_decrypt_tool.database_matcher import enumerate_session_dbs, find_matching_database
from common_utils import display_error_and_exit, parse_timestamp, format_timestamp, truncate_text

# 初始化日志
setup_exe_logging()
logger = get_exe_logger(__name__)


# ==================== 目录查找辅助函数 ====================

SKIP_DIRS = {'all users', 'applet', 'wmpf', 'backup', 'config', 'cache'}


def _find_session_db_in_account_dir(base_path: Path) -> Optional[Path]:
    """在账号目录下查找 session.db
    
    Args:
        base_path: 账号目录路径
        
    Returns:
        session.db 路径，未找到返回 None
    """
    if not base_path.exists() or not base_path.is_dir():
        return None
    
    direct_paths = [
        base_path / 'db_storage' / 'session' / 'session.db',
        base_path / 'db_storage' / 'session.db',
    ]
    
    for path in direct_paths:
        if path.exists():
            return path
    return None


def _find_account_dir(base_path: Path, account_id: Optional[str] = None) -> Optional[Path]:
    """查找包含有效 session.db 的账号目录
    
    统一的账号目录查找逻辑，合并了原有的多个查找方法
    
    Args:
        base_path: 基础目录路径
        account_id: 可选的账号ID，用于匹配目录名
        
    Returns:
        找到的账号目录路径，未找到返回 None
    """
    if not base_path.exists() or not base_path.is_dir():
        return None
    
    try:
        for sub_dir in base_path.iterdir():
            if not sub_dir.is_dir():
                continue
            
            dir_name_lower = sub_dir.name.lower()
            if dir_name_lower in SKIP_DIRS:
                continue
            
            # 如果指定了账号ID，检查目录名是否匹配
            if account_id and account_id.lower() not in dir_name_lower:
                continue
            
            # 检查是否包含有效的 session.db
            if _find_session_db_in_account_dir(sub_dir):
                return sub_dir
                
    except (PermissionError, OSError) as e:
        logger.debug(f"[账号查找] 遍历目录失败: {base_path}, 错误: {e}")
    
    return None


# ==================== SimpleMonitor 类 ====================

class SimpleMonitor:
    """简化版监控器 - 一键启动"""

    def __init__(self):
        self.pid: Optional[int] = None
        self.account_id: Optional[str] = None
        self.data_path: Optional[str] = None
        self.db_key: Optional[str] = None
        self.handle: Optional[int] = None
        self.groups: List[Dict] = []
        self.temp_dir: Optional[str] = None
        self.decrypted_session_db: Optional[str] = None
        self.decrypted_contact_db: Optional[str] = None
        self.use_static_mode: bool = False
        self.nickname_cache: Dict[str, str] = {}
        self._group_db_mapping: Dict[str, str] = {}  # 群ID到数据库路径的映射缓存

    @property
    def key(self) -> Optional[str]:
        """密钥属性别名（兼容测试）"""
        return self.db_key

    def get_groups_list(self) -> List[Dict]:
        """获取群列表（兼容测试接口）
        
        Returns:
            群信息列表，每个元素包含 group_name, group_id 等
        """
        if self.groups:
            return self.groups
        
        # 如果groups为空，尝试从数据库获取
        if hasattr(self, '_wcdb') and self._wcdb:
            try:
                groups = self._get_groups_from_session()
                return groups
            except Exception as e:
                logger.warning(f"获取群列表失败: {e}")
        
        return []

    def get_history_messages(self, group_id: str = None, limit: int = 100) -> List[Dict]:
        """获取历史消息（兼容测试接口）
        
        Args:
            group_id: 群ID，如果为None则获取所有群的消息
            limit: 消息数量限制
            
        Returns:
            消息列表
        """
        messages = []
        
        if group_id:
            messages = self._fetch_history_messages(group_id)
        else:
            # 获取所有群的消息
            groups = self.get_groups_list()
            for group in groups[:5]:  # 限制群数量避免过多
                gid = group.get('group_id') or group.get('username')
                if gid:
                    msgs = self._fetch_history_messages(gid)
                    messages.extend(msgs)
        
        return messages[:limit]

    # ==================== 内部辅助方法 ====================

    @staticmethod
    def _decompress_zstd_data(data: bytes) -> Optional[str]:
        """统一的 zstd 解压逻辑

        Args:
            data: 可能是 zstd 压缩的字节数据

        Returns:
            解压后的字符串，解压失败返回 None
        """
        if not data or not isinstance(data, bytes):
            return None
        try:
            import zstandard as zstd
            if data.startswith(ZSTD_MAGIC):
                decompressor = zstd.ZstdDecompressor()
                return decompressor.decompress(data).decode('utf-8', errors='replace')
        except Exception:
            pass
        return None

    @staticmethod
    def _get_msg_timestamp(msg: Dict) -> int:
        """统一从消息字典中解析时间戳

        处理 create_time / createTime 两种字段名。
        """
        return parse_timestamp(msg.get('create_time') or msg.get('createTime') or 0)

    def _save_message_to_storage(self, processed: Dict, storage) -> bool:
        """统一保存单条消息到存储

        Args:
            processed: 经 _process_single_message 处理后的消息字典
            storage: 消息存储实例

        Returns:
            True 保存成功，False 失败
        """
        try:
            storage.save_message(
                sender_nickname=processed['sender'],
                message_content=processed['content'],
                send_time=datetime.fromtimestamp(processed['time_int']),
                group_name=processed['group_name'],
                group_id=processed['group_id'],
                sender_id=processed['sender_wxid']
            )
            return True
        except Exception as e:
            logger.warning(f"[监控] 保存消息失败: {e}")
            return False

    # ==================== 显示辅助方法 ====================
    
    def print_header(self):
        """显示头部"""
        print()
        print("=" * 60)
        print("          微信群消息监听系统 v1.0")
        print("=" * 60)
        print()

    def print_step(self, step_name: str, status: str, detail: str = ""):
        """显示步骤状态"""
        status_symbols = {
            'done': '[OK]',
            'doing': '[..]',
            'fail': '[FAIL]'
        }
        symbol = status_symbols.get(status, '[??]')
        
        line = f"  {symbol} {step_name}"
        if detail:
            line += f": {detail}"
        print(line)

    def _wait_exit(self):
        """等待退出"""
        print()
        input("  按 Enter 键退出...")

    # ==================== 步骤1: 进程检测 ====================
    
    def step1_detect_process(self) -> bool:
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

    # ==================== 步骤2: 账号识别 ====================
    
    def step2_detect_account(self) -> bool:
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

            # 查找包含有效 db_storage 的账号目录
            for base_dir in detected_dirs:
                account_dir = _find_account_dir(Path(base_dir), self.account_id)
                if account_dir:
                    self.data_path = str(account_dir)
                    break

            if not self.data_path:
                # 如果找不到有效的 db_storage，使用原始逻辑
                if result.get('data_path'):
                    self.data_path = result['data_path']
                else:
                    self.data_path = self._find_legacy_account_dir(detected_dirs, self.account_id)

            account_display = truncate_text(self.account_id, 20)
            self.print_step("账号识别", "done", account_display)
            logger.info(f"[步骤2] 检测到账号: {self.account_id}, 数据路径: {self.data_path}")
            return True
        else:
            # 账号检测失败时，尝试在检测到的目录中查找包含有效数据库的账号目录
            for base_dir in detected_dirs:
                account_dir = _find_account_dir(Path(base_dir))
                if account_dir:
                    self.data_path = str(account_dir)
                    # 从路径中提取账号ID
                    dir_name = account_dir.name
                    if dir_name.startswith('wxid_') or dir_name.startswith('wl_'):
                        self.account_id = dir_name
                    self.print_step("账号识别", "done", f"自动发现: {self.account_id or '未知账号'}")
                    logger.info(f"[步骤2] 自动发现账号目录: {self.data_path}")
                    return True
            
            # 最后降级：使用第一个检测到的目录
            self.data_path = detected_dirs[0]
            self.print_step("账号识别", "done", "使用默认目录")
            logger.warning(f"[步骤2] 未能找到有效账号目录，使用默认: {self.data_path}")
            return True

    def _find_legacy_account_dir(self, base_dirs: List[str], account_id: str) -> Optional[str]:
        """查找账号对应的数据目录（旧版兼容）"""
        for base_dir in base_dirs:
            try:
                for item in os.listdir(base_dir):
                    item_path = os.path.join(base_dir, item)
                    if os.path.isdir(item_path) and item.startswith(account_id):
                        return item_path
            except (PermissionError, OSError):
                continue
        return base_dirs[0] if base_dirs else None

    # ==================== 步骤3: 密钥获取 ====================
    
    def step3_get_key(self) -> bool:
        """步骤3: 密钥获取 - 每次启动重新获取，不使用旧密钥"""
        self.print_step("密钥获取", "doing")

        exe_dir = get_exe_dir()
        key_store_path = exe_dir / 'output' / 'account_keys.json'

        # 清除旧的密钥文件，确保每次启动都重新获取
        if key_store_path.exists():
            try:
                key_store_path.unlink()
                logger.info("[步骤3] 已清除旧密钥文件，将重新获取")
                print("    检查旧密钥文件: 已清除，将重新获取")
            except OSError as e:
                logger.warning(f"[步骤3] 清除旧密钥文件失败: {e}")
        else:
            logger.info("[步骤3] 无旧密钥文件，将重新获取")
            print("    检查旧密钥文件: 无旧文件，将重新获取")

        logger.info("[步骤3] 尝试Hook注入获取密钥...")

        print()
        print("  [!] 需要重启微信以获取密钥")
        print("  [!] 请在微信重启后手动登录")
        print("  [!] 整体超时保护: 120秒，超时后将提供手动输入选项")
        print()

        # 尝试 Hook 注入获取密钥
        if self._try_fetch_key_via_hook():
            return True

        # 所有方式都失败，提供手动输入降级
        self.print_step("密钥获取", "fail", "自动获取未成功")
        print()
        print("  自动获取密钥失败，您可以：")
        print("  1. 手动输入64位十六进制密钥")
        print("  2. 确保 output/account_keys.json 文件存在且包含当前账号密钥")
        print("  3. 重新运行程序并确保微信已正常登录")
        print()
        print("  常见原因：")
        print("  - 微信未正确安装或安装路径异常")
        print("  - 微信版本过新，Hook暂不支持")
        print("  - 需要管理员权限运行")
        print()

        manual_key = self._prompt_manual_key()
        if manual_key:
            self.db_key = manual_key
            self.print_step("密钥获取", "done", "手动输入")
            logger.info("[步骤3] 使用手动输入密钥（降级）")
            self._save_key()
            return True

        print()
        print("  未提供密钥，程序将退出。")
        print("  请通过以下方式获取密钥后重试：")
        print("  - 使用其他工具导出密钥")
        print("  - 检查 output/account_keys.json 是否存在")
        print()
        return False

    def _try_fetch_key_via_hook(self) -> bool:
        """尝试通过 Hook 注入获取密钥"""
        try:
            from wechat_decrypt_tool.key_service import WeChatKeyFetcher

            fetcher = WeChatKeyFetcher()
            logger.info("[步骤3] WeChatKeyFetcher 实例化成功，开始调用 fetch_db_key()...")

            result = fetcher.fetch_db_key()
            logger.info(f"[步骤3] fetch_db_key() 返回结果: {type(result).__name__}")

            if result:
                db_key = result.get('key') or result.get('db_key')
                logger.info(f"[步骤3] 提取到的密钥长度: {len(str(db_key)) if db_key else 0}")
                if db_key and len(str(db_key)) == 64:
                    self.db_key = str(db_key).lower()

                    # 主动匹配数据库（替换旧逻辑：不再依赖初始目录选择）
                    print(f"  [..] 正在匹配密钥与数据库（遍历所有数据目录）...", flush=True)
                    logger.info("[步骤3] 开始主动匹配密钥与数据库")
                    
                    from wechat_decrypt_tool.wechat_detection import auto_detect_wechat_data_dirs
                    detected_dirs = auto_detect_wechat_data_dirs()
                    candidates = enumerate_session_dbs(detected_dirs)
                    match_result = find_matching_database(self.db_key, candidates)
                    
                    if match_result.matched_path:
                        # 更新为匹配到的正确数据目录
                        old_data_path = self.data_path
                        self.data_path = match_result.matched_data_path
                        self.print_step("密钥获取", "done", f"Hook注入成功，匹配数据库: {match_result.matched_path} (第{match_result.verified_at_retry}次重试)")
                        logger.info(f"[步骤3] Hook注入成功，匹配数据库成功: 旧目录={old_data_path}, 新目录={self.data_path}, 数据库={match_result.matched_path}")
                        self._save_key()
                        return True
                    else:
                        # 所有尝试都失败
                        logger.warning("[步骤3] 密钥与所有session.db都不匹配，尝试过的路径:")
                        for tried in match_result.tried_paths:
                            logger.warning(f"  - {tried['path']}: {tried['mode']}")
                        print(f"  [!] 密钥与所有数据目录中的session.db都不匹配，请检查密钥是否正确")
                        print(f"      已尝试 {len(match_result.tried_paths)} 个候选数据库")
                else:
                    logger.warning(f"[步骤3] Hook返回密钥格式无效: len={len(str(db_key)) if db_key else 0}")
                    print(f"  [!] 密钥格式无效，长度: {len(str(db_key)) if db_key else 0}")

        except ImportError as e:
            logger.error(f"[步骤3] wx_key模块不可用: {e}")
            print(f"  [!] wx_key模块导入失败: {e}")
        except TimeoutError as e:
            logger.error(f"[步骤3] Hook获取密钥超时: {e}")
            print()
            print(f"  [!] 获取密钥超时: {e}")
            print("  [!] 可能原因: 微信启动卡住、Hook初始化挂起或轮询无响应")
            print()
            # 超时降级：提供手动输入密钥选项
            manual_key = self._prompt_manual_key()
            if manual_key:
                self.db_key = manual_key
                self.print_step("密钥获取", "done", "手动输入")
                logger.info("[步骤3] 使用手动输入密钥（超时降级）")
                self._save_key()
                return True
        except RuntimeError as e:
            logger.error(f"[步骤3] Hook运行时错误: {e}")
            print(f"  [!] Hook运行时错误: {e}")
        except Exception as e:
            logger.error(f"[步骤3] Hook注入失败: {e}")
            logger.error(f"[步骤3] 详细错误信息:\n{traceback.format_exc()}")
            print(f"  [!] Hook注入失败: {e}")
            print(f"  [!] 详细信息请查看日志文件")

        return False

    def _prompt_manual_key(self) -> Optional[str]:
        """提示用户手动输入64位十六进制密钥"""
        try:
            print("  请输入64位十六进制密钥（按 Enter 跳过）: ", end="", flush=True)
            raw = input().strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if not raw:
            return None

        # 清理输入：去除 0x 前缀、空格、换行
        cleaned = raw.lower().replace("0x", "").replace(" ", "").replace("\n", "").replace("\r", "")
        # 只保留十六进制字符
        cleaned = re.sub(r"[^0-9a-f]", "", cleaned)

        if len(cleaned) != 64:
            print(f"  [!] 密钥长度无效: 需要64位十六进制，当前输入长度: {len(cleaned)}")
            return None

        logger.info("[步骤3] 用户手动输入密钥，长度验证通过")
        return cleaned

    def _verify_key_matches_db(self, db_path: str, db_key: str) -> bool:
        """验证密钥是否匹配数据库（通过Page1 HMAC校验）

        只读取数据库第1页（4096字节），用HMAC校验密钥是否匹配。
        耗时<1秒，不会修改数据库文件。

        Args:
            db_path: 数据库文件路径
            db_key: 64位十六进制密钥字符串

        Returns:
            True=密钥匹配, False=密钥不匹配
        """
        import hashlib
        import hmac as hmac_mod
        import struct

        PAGE_SIZE = 4096
        SALT_SIZE = 16
        IV_SIZE = 16
        HMAC_SIZE = 64
        RESERVE_SIZE = IV_SIZE + HMAC_SIZE
        KEY_SIZE = 32

        try:
            # 读取第1页
            with open(db_path, 'rb') as f:
                page1 = f.read(PAGE_SIZE)

            if len(page1) < PAGE_SIZE:
                logger.debug(f"[密钥验证] 文件太小: {len(page1)} bytes")
                return False

            # 检查是否已经是明文SQLite
            if page1.startswith(b"SQLite format 3\x00"):
                logger.debug(f"[密钥验证] 数据库已是明文SQLite，无需密钥")
                return True

            # 提取salt
            salt = page1[:SALT_SIZE]
            salt_xor = bytes(b ^ 0x3A for b in salt)  # 缓存，避免重复计算

            # 将hex密钥转为bytes
            key_bytes = bytes.fromhex(db_key)

            # 尝试两种模式：raw enc_key 和 passphrase
            # 模式1: key是raw enc_key
            mac_key_1 = hashlib.pbkdf2_hmac("sha512", key_bytes, salt_xor, 2, dklen=KEY_SIZE)

            # 模式2: key是passphrase，需要先derive
            enc_key_2 = hashlib.pbkdf2_hmac("sha512", key_bytes, salt, 256000, dklen=KEY_SIZE)
            mac_key_2 = hashlib.pbkdf2_hmac("sha512", enc_key_2, salt_xor, 2, dklen=KEY_SIZE)

            # 计算Page1的HMAC
            stored_hmac = page1[PAGE_SIZE - HMAC_SIZE: PAGE_SIZE]
            offset = SALT_SIZE  # page1从salt后开始
            data_end = PAGE_SIZE - RESERVE_SIZE + IV_SIZE
            page_data = page1[offset:data_end]  # 缓存，避免重复切片

            for mode, mac_key in [("raw_key", mac_key_1), ("passphrase", mac_key_2)]:
                mac = hmac_mod.new(mac_key, digestmod=hashlib.sha512)
                mac.update(page_data)
                mac.update(struct.pack('<I', 1))  # page number
                expected_hmac = mac.digest()

                if hmac_mod.compare_digest(stored_hmac, expected_hmac):
                    logger.info(f"[密钥验证] 密钥匹配数据库: mode={mode}, path={db_path}")
                    return True

            logger.debug(f"[密钥验证] 密钥不匹配数据库: {db_path}")
            return False

        except Exception as e:
            logger.warning(f"[密钥验证] 验证异常: {e}")
            return False

    def _find_all_session_dbs(self) -> List[str]:
        """查找所有可能的 session.db 路径

        Returns:
            session.db 路径列表
        """
        from wechat_decrypt_tool.wechat_detection import detect_wechat_installation

        all_paths = []

        def _add_if_new(p: Path):
            """添加路径到列表（去重）"""
            s = str(p)
            if p.exists() and s not in all_paths:
                all_paths.append(s)

        def _rglob_session_dbs(base_dir: Path):
            """在目录下递归搜索 session.db"""
            if not base_dir.exists() or not base_dir.is_dir():
                return
            try:
                for item in base_dir.rglob('session.db'):
                    path_str = str(item).lower()
                    if 'db_storage' in path_str or 'session' in str(item.parent).lower():
                        _add_if_new(item)
            except (PermissionError, OSError) as e:
                logger.debug(f"[session.db搜索] rglob搜索失败: {base_dir}, 错误: {e}")

        # 1. 当前 data_path 下的 session.db（直接路径，优先）
        if self.data_path:
            data_path_obj = Path(self.data_path)
            session_db = _find_session_db_in_account_dir(data_path_obj)
            if session_db:
                _add_if_new(session_db)

        # 2. 搜索所有微信数据目录（递归）
        try:
            detection = detect_wechat_installation()
            wechat_data_dirs = detection.get('data_dirs', [])

            for data_dir in wechat_data_dirs:
                data_dir_obj = Path(data_dir)
                if data_dir_obj.exists():
                    _rglob_session_dbs(data_dir_obj)

        except Exception as e:
            logger.warning(f"[session.db搜索] 搜索微信数据目录失败: {e}")

        logger.info(f"[session.db搜索] 找到 {len(all_paths)} 个session.db路径")
        return all_paths

    def _try_match_any_session_db(self, exclude_path: Optional[str] = None) -> bool:
        """搜索所有 session.db，找到与密钥匹配的，找到则更新 data_path

        Args:
            exclude_path: 跳过已验证的路径

        Returns:
            True=找到匹配的数据库，False=未找到
        """
        all_session_dbs = self._find_all_session_dbs()
        for db_path in all_session_dbs:
            if exclude_path and db_path == exclude_path:
                continue
            logger.info(f"[密钥验证] 尝试: {db_path}")
            if self._verify_key_matches_db(db_path, self.db_key):
                logger.info(f"[密钥验证] 找到匹配的session.db: {db_path}")
                print(f"  [OK] 找到密钥匹配的数据库: {db_path}")
                new_data_path = str(Path(db_path).parent.parent.parent)
                if Path(new_data_path).exists():
                    logger.info(f"[密钥验证] 更新data_path: {self.data_path} -> {new_data_path}")
                    self.data_path = new_data_path
                    return True
        return False

    def _verify_key_and_find_matching_db(self) -> bool:
        """验证密钥是否匹配当前 session.db，不匹配则搜索其他路径

        两轮验证：首轮 + 等待5秒后重试。

        Returns:
            True=找到匹配的数据库, False=未找到
        """
        if not self.db_key:
            return False

        for attempt in range(2):
            if attempt > 0:
                # 第2轮：等待后重试
                logger.info("[密钥验证] 首次验证失败，等待5秒后重试...")
                print(f"  等待微信更新数据库（5秒）...", flush=True)
                time.sleep(5)

            session_db_path = self._find_session_db()
            if not session_db_path:
                logger.warning("[密钥验证] 未找到session.db")
                if attempt == 0:
                    continue  # 第一轮失败，继续等待重试
                return False

            # 验证当前 session.db
            if self._verify_key_matches_db(session_db_path, self.db_key):
                logger.info("[密钥验证] 密钥匹配当前session.db")
                return True

            if attempt == 0:
                logger.warning(f"[密钥验证] 密钥不匹配当前session.db: {session_db_path}")
                print(f"  [!] 密钥与当前session.db不匹配，搜索其他数据目录...")

            # 搜索所有 session.db
            if self._try_match_any_session_db(exclude_path=session_db_path):
                return True

        logger.warning("[密钥验证] 所有session.db均不匹配当前密钥")
        print(f"  [!] 未找到密钥匹配的数据库")
        return False

    def _save_key(self):
        """保存密钥到存储"""
        exe_dir = get_exe_dir()
        key_store_path = exe_dir / 'output' / 'account_keys.json'

        key_store_path.parent.mkdir(parents=True, exist_ok=True)

        store = {'accounts': {}}
        if key_store_path.exists():
            try:
                store = json.loads(key_store_path.read_text(encoding='utf-8'))
                if 'accounts' not in store:
                    store['accounts'] = {}
            except (json.JSONDecodeError, OSError):
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
        except OSError as e:
            logger.warning(f"[步骤3] 保存密钥失败: {e}")

    # ==================== 步骤4: 数据库连接 ====================
    
    def step4_connect_db(self) -> bool:
        """步骤4: 数据库连接"""
        self.print_step("数据库连接", "doing")

        if not self.db_key:
            self.print_step("数据库连接", "fail", "无密钥")
            return False

        # 步骤3已经完成匹配，data_path已经是正确的了
        print(f"  等待微信初始化完成...")
        time.sleep(3)

        # 查找 session.db（此时 data_path 已经匹配正确）
        session_db_path = self._find_session_db()
        if not session_db_path:
            self.print_step("数据库连接", "fail", "session.db不存在")
            return False

        # 首先尝试静态解密
        print(f"  使用静态解密方式...")
        logger.info(f"[步骤4] 尝试静态解密方式连接数据库（data_path已在步骤3匹配完成）")

        static_success = False
        try:
            if self._connect_via_static_decrypt(session_db_path):
                self.print_step("数据库连接", "done", "静态解密成功")
                logger.info(f"[步骤4] 静态解密连接成功")
                static_success = True
        except Exception as e:
            logger.warning(f"[步骤4] 静态解密失败: {e}")

        # 尝试 WCDB 连接
        print(f"  尝试 WCDB 连接...", flush=True)
        logger.info(f"[步骤4] 尝试WCDB实时连接")

        self._try_wcdb_connection(session_db_path)

        # 只要静态解密成功，就返回 True
        return static_success

    def _try_wcdb_connection(self, session_db_path: str):
        """尝试 WCDB 连接"""
        import threading
        
        try:
            from wechat_decrypt_tool.wcdb_realtime import open_account

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
                logger.warning(f"[步骤4] WCDB连接超时(10秒)，使用静态模式")
                self.handle = None
                print(f"  WCDB 连接超时，将使用静态模式", flush=True)
            elif exception[0]:
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

    def _connect_via_static_decrypt(self, session_db_path: str) -> bool:
        """通过静态解密方式连接数据库"""
        from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor

        self.temp_dir = tempfile.mkdtemp(prefix="wechat_monitor_")

        decryptor = WeChatDatabaseDecryptor(self.db_key)
        self.decrypted_session_db = os.path.join(self.temp_dir, "session.db")

        if not decryptor.decrypt_database(session_db_path, self.decrypted_session_db):
            return False

        print(f"  session.db 解密成功")

        # 解密 contact.db
        contact_db_path = self._find_contact_db()
        if contact_db_path:
            self.decrypted_contact_db = os.path.join(self.temp_dir, "contact.db")
            if not decryptor.decrypt_database(contact_db_path, self.decrypted_contact_db):
                self.decrypted_contact_db = None
        else:
            self.decrypted_contact_db = None

        self.use_static_mode = True

        # 加载昵称缓存
        self._load_nickname_cache()

        # 验证解密后的数据库
        try:
            with sqlite3.connect(self.decrypted_session_db) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
                cursor.fetchone()
                return True
        except sqlite3.Error:
            return False

    def _load_nickname_cache(self):
        """从 contact.db 加载昵称缓存"""
        self.nickname_cache = {}

        if not self.decrypted_contact_db or not os.path.exists(self.decrypted_contact_db):
            logger.warning("[昵称缓存] contact.db 不存在，无法加载昵称")
            return

        try:
            with sqlite3.connect(self.decrypted_contact_db) as conn:
                cursor = conn.cursor()
                # 检查表是否存在
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='contact'")
                if not cursor.fetchone():
                    logger.warning("[昵称缓存] contact 表不存在")
                    return

                cursor.execute("SELECT username, nick_name, remark FROM contact")

                count = 0
                for row in cursor.fetchall():
                    username, nick_name, remark = row
                    display_name = remark or nick_name or ''
                    if display_name and username:
                        self.nickname_cache[username] = display_name
                        count += 1

                logger.info(f"[昵称缓存] 已加载 {count} 个昵称映射")
                print(f"  已加载 {count} 个联系人昵称")

        except Exception as e:
            logger.warning(f"[昵称缓存] 加载失败: {e}")

    def _get_display_name(self, wxid: str) -> str:
        """获取 wxid 对应的显示名称"""
        return self.nickname_cache.get(wxid, wxid)

    def _find_contact_db(self) -> Optional[str]:
        """查找 contact.db 路径"""
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
        """查找 session.db 路径

        按优先级依次在候选基础目录下查找：
        1. data_path 本身（账号目录）
        2. data_path 的子目录（根目录下的账号子目录）
        3. data_path / WeChat Files 子目录
        """
        if not self.data_path:
            logger.warning("[session.db查找] data_path 未设置")
            return None

        data_path_obj = Path(self.data_path)
        if not data_path_obj.exists():
            logger.warning(f"[session.db查找] 路径不存在: {self.data_path}")
            return None

        # 候选基础目录列表（按优先级）
        base_candidates = [data_path_obj]
        wechat_files = data_path_obj / 'WeChat Files'
        if wechat_files.exists() and wechat_files.is_dir():
            base_candidates.append(wechat_files)

        for base in base_candidates:
            # 方式1：base 本身就是账号目录
            session_db = _find_session_db_in_account_dir(base)
            if session_db:
                logger.info(f"[session.db查找] 找到: {session_db}")
                return str(session_db)

            # 方式2：base 的子目录是账号目录
            account_dir = _find_account_dir(base)
            if account_dir:
                session_db = _find_session_db_in_account_dir(account_dir)
                if session_db:
                    logger.info(f"[session.db查找] 在 {base.name} 子目录找到: {session_db}")
                    return str(session_db)

        logger.warning(f"[session.db查找] 未找到 session.db，搜索路径: {self.data_path}")
        return None

    # ==================== 步骤5: 选择群聊 ====================
    
    def step5_select_group(self):
        """步骤5: 选择群聊"""
        print()

        if self.use_static_mode:
            return self._select_group_static()
        else:
            return self._select_group_wcdb()

    def _select_group_wcdb(self):
        """使用 WCDB 方式获取群聊列表"""
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
                name = truncate_text(name, 30)
                print(f"    {i:2d}. {name}")

            if len(self.groups) > 30:
                print(f"\n  ... 还有 {len(self.groups) - 30} 个群聊")

            print()

        except WCDBRealtimeError as e:
            print(f"  获取群聊列表失败: {e}")
            return None

        return self._get_user_choice()

    def _select_group_static(self):
        """使用静态解密方式选择群聊"""
        self.groups = self._get_groups_from_session()

        print("  =========== 选择群聊 ===========")
        print()

        if not self.groups:
            print("  未能获取群聊列表，请检查数据库")
            return None

        print(f"  已加载 {len(self.groups)} 个群聊")
        print("  请输入群名称关键词进行搜索")
        print()

        return self._search_group_interactive()

    def _search_group_interactive(self):
        """交互式群聊搜索"""
        while True:
            try:
                keyword = input("  请输入群名称关键词: ").strip()

                if not keyword:
                    print("  已取消选择")
                    return None

                matched_groups = self._search_groups_in_contact(keyword)

                if not matched_groups:
                    print(f"  未找到包含 '{keyword}' 的群聊，请重试")
                    print()
                    continue

                print()
                print(f"  找到 {len(matched_groups)} 个匹配的群聊:")
                print()

                for i, group in enumerate(matched_groups[:20], 1):
                    name = group.get('displayName', '') or group.get('username', '')
                    name = truncate_text(name, 45)
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

    def _get_groups_from_session(self) -> List[Dict]:
        """从 SessionTable 和 contact 表获取群聊列表"""
        try:
            # 1. 从 contact 表获取群昵称
            group_names = {}
            if self.decrypted_contact_db and os.path.exists(self.decrypted_contact_db):
                try:
                    with sqlite3.connect(self.decrypted_contact_db) as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            SELECT username, nick_name, remark
                            FROM contact
                            WHERE username LIKE '%@chatroom'
                        """)
                        for row in cursor.fetchall():
                            username, nick_name, remark = row
                            display_name = remark or nick_name or ''
                            if display_name:
                                group_names[username] = display_name
                except sqlite3.Error:
                    pass

            # 2. 从 SessionTable 获取群列表
            with sqlite3.connect(self.decrypted_session_db) as conn:
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

                return groups

        except Exception as e:
            logger.warning(f"[步骤5] SessionTable查询失败: {e}")
            return []

    def _search_groups_in_contact(self, keyword: str) -> List[Dict]:
        """从 contact.db 搜索群聊"""
        matched_groups = []

        if self.decrypted_contact_db and os.path.exists(self.decrypted_contact_db):
            try:
                with sqlite3.connect(self.decrypted_contact_db) as conn:
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

                    for row in cursor.fetchall():
                        username, nick_name, remark = row
                        display_name = remark or nick_name or username
                        matched_groups.append({
                            'username': username,
                            'displayName': f"{display_name} ({username})" if display_name != username else username
                        })

            except sqlite3.Error as e:
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

    # ==================== 消息处理 ====================
    
    def _is_non_text_message(self, content: str) -> bool:
        """判断是否为非纯文字消息（需要完全过滤的）"""
        if not content or not content.strip():
            return True

        content_stripped = content.strip()

        # XML 格式消息（图片、链接、文件等）
        if content_stripped.startswith('<?xml') or content_stripped.startswith('<msg'):
            return True

        # 检查是否包含图片标签或其他非文字标签
        non_text_indicators = ['<img', '<videomsg', '<voicemsg', '<appmsg', '<emoji', '<location']
        content_lower = content_stripped.lower()
        for indicator in non_text_indicators:
            if indicator in content_lower:
                return True

        return False

    def _clean_message_content(self, content: str) -> str:
        """清理消息内容，去除表情包标记，保留文字"""
        if not content:
            return ""

        # 去除所有位置的表情包标记（如 [太阳]、[红包] 等）
        cleaned = re.sub(r'\s*\[[^\]]+\]\s*', ' ', content)

        # 清理多余的空格
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        # 如果清理后为空，返回原始内容
        return cleaned if cleaned.strip() else content.strip()

    def decode_message(self, raw_content: Any) -> str:
        """解码消息内容（处理 zstd 压缩和 hex 字符串）"""
        if raw_content is None:
            return ""

        # 处理 bytes 类型
        if isinstance(raw_content, bytes):
            decompressed = self._decompress_zstd_data(raw_content)
            if decompressed is not None:
                return decompressed
            return raw_content.decode('utf-8', errors='replace')

        # 处理字符串类型
        text = str(raw_content).strip()

        # 检查是否为 hex 字符串（zstd 压缩数据）
        if len(text) >= 16 and len(text) % 2 == 0:
            try:
                raw = bytes.fromhex(text)
                decompressed = self._decompress_zstd_data(raw)
                if decompressed is not None:
                    return decompressed
            except Exception:
                pass

        return text

    def _process_single_message(self, msg: Dict, group_name: str, group_id: str) -> Optional[Dict]:
        """处理单条消息，返回处理后的消息信息
        
        Args:
            msg: 原始消息字典
            group_name: 群名称
            group_id: 群ID
            
        Returns:
            处理后的消息信息字典，如果消息被过滤则返回 None
        """
        msg_time_int = self._get_msg_timestamp(msg)

        sender_wxid = msg.get('sender_username') or msg.get('sender') or '未知'
        sender = self._get_display_name(sender_wxid)

        raw_content = msg.get('message_content') or msg.get('content') or ''
        content = self.decode_message(raw_content)

        # 过滤非纯文字消息
        if self._is_non_text_message(content):
            return None

        # 清理表情包标记
        content = self._clean_message_content(content)

        if len(content.strip()) < 1:
            return None

        return {
            'time_int': msg_time_int,
            'time_str': format_timestamp(msg_time_int),
            'sender': sender,
            'content': content,
            'sender_wxid': sender_wxid,
            'group_name': group_name,
            'group_id': group_id
        }

    # ==================== 监控 ====================
    
    def start_monitoring(self, target_group: Dict):
        """开始监控"""
        group_id = target_group.get('username', '')
        group_name = target_group.get('displayName', '') or group_id
        group_name = truncate_text(group_name, 25)

        print()
        print("=" * 60)
        print(f"  监控: {group_name}")
        print("  按 Ctrl+C 停止")
        print("=" * 60)
        print()

        from wechat_decrypt_tool.message_storage import get_message_storage

        storage = get_message_storage()

        # 轮询配置
        current_interval = POLL_INTERVAL_DEFAULT
        poll_count = 0
        saved_count = 0

        # 记录已存在的消息时间戳
        last_create_time = 0

        # 获取历史消息
        print("  正在获取历史消息...", flush=True)

        messages = self._fetch_history_messages(group_id)

        if messages:
            self._display_and_save_history(messages, group_name, group_id, storage)
            # 更新最新消息时间戳
            for msg in messages:
                msg_time_int = parse_timestamp(msg.get('create_time') or msg.get('createTime') or 0)
                if msg_time_int > last_create_time:
                    last_create_time = msg_time_int

            time_str = format_timestamp(last_create_time, '%Y-%m-%d %H:%M:%S') if last_create_time else "无"
            print(f"  当前最新消息时间: {time_str}")

        print(f"  自适应轮询: 最小 {POLL_INTERVAL_MIN} 秒, 最大 {POLL_INTERVAL_MAX} 秒")
        print()

        # 开始监控循环
        try:
            last_create_time = self._monitoring_loop(
                group_id, group_name, storage, last_create_time
            )
        except KeyboardInterrupt:
            print('\n\n[监听已停止]')
            print(f'[统计] 轮询次数: {poll_count}, 最终间隔: {current_interval:.1f}秒')
            if saved_count > 0:
                print(f'[已保存 {saved_count} 条消息到数据库]')

    def _fetch_history_messages(self, group_id: str) -> List[Dict]:
        """获取历史消息"""
        messages = []
        
        # 优先尝试 WCDB 实时方式
        if self.handle and self.handle > 0:
            try:
                from wechat_decrypt_tool.wcdb_realtime import get_messages
                messages = get_messages(self.handle, group_id, limit=100)
                if messages:
                    print(f"  [OK] 使用 WCDB 获取到 {len(messages)} 条历史消息")
            except Exception as e:
                logger.warning(f"[监控] WCDB 获取消息失败: {e}")

        # 如果 WCDB 失败，尝试静态解密
        if not messages and self.use_static_mode:
            print("  [..] WCDB 方式失败，尝试静态解密...")
            messages = self._get_messages_static(group_id, limit=100)

        return messages

    def _display_and_save_history(self, messages: List[Dict], group_name: str,
                                    group_id: str, storage) -> int:
        """显示并保存历史消息"""
         # 显示历史消息（最新的5条）
        print(f"  最近 {min(5, len(messages))} 条历史消息:")
        print()

        # messages 按 create_time 升序排序，最新消息在末尾，取最后5条
        for msg in messages[-min(5, len(messages)):]:
            processed = self._process_single_message(msg, group_name, group_id)
            if processed:
                print(f"    [{processed['time_str']}] {processed['sender']}: {processed['content']}")
                print()

        print()

        # 保存历史消息到数据库
        history_saved = 0
        for msg in messages:
            processed = self._process_single_message(msg, group_name, group_id)
            if not processed:
                continue
            if self._save_message_to_storage(processed, storage):
                history_saved += 1

        if history_saved > 0:
            print(f"  [OK] 已保存 {history_saved} 条历史消息到数据库")
            # 触发看板刷新
            self._trigger_dashboard_refresh()
            print()

        return history_saved

    def _monitoring_loop(self, group_id: str, group_name: str, storage, 
                          last_create_time: int) -> int:
        """监控循环"""
        current_interval = POLL_INTERVAL_DEFAULT
        poll_count = 0
        saved_count = 0
        consecutive_no_new = 0

        while True:
            # 等待
            time.sleep(current_interval)
            poll_count += 1

            # 获取最新消息
            try:
                new_messages = self._fetch_new_messages(group_id)
            except Exception as e:
                logger.warning(f"[监控] 获取消息失败: {e}")
                continue

            # 找到最新的时间戳
            max_time_in_batch = 0
            for msg in new_messages:
                msg_time_int = parse_timestamp(msg.get('create_time') or msg.get('createTime') or 0)
                if msg_time_int > max_time_in_batch:
                    max_time_in_batch = msg_time_int

            # 调试：显示轮询状态（每30次）
            if poll_count % 30 == 0:
                time_str = format_timestamp(max_time_in_batch) if max_time_in_batch else "无"
                logger.debug(f"[轮询 {poll_count}] 间隔: {current_interval:.1f}s, 消息数: {len(new_messages)}, 最新: {time_str}")

            # 如果有新消息
            if max_time_in_batch > last_create_time:
                old_last_time = last_create_time
                last_create_time = max_time_in_batch

                consecutive_no_new = 0
                current_interval = max(POLL_INTERVAL_MIN, current_interval * 0.5)

                # 输出新消息
                saved_count = self._output_new_messages(
                    new_messages, group_name, group_id, storage, 
                    old_last_time, saved_count
                )
            else:
                consecutive_no_new += 1
                current_interval = min(POLL_INTERVAL_MAX, current_interval * 1.5)

        return last_create_time

    def _fetch_new_messages(self, group_id: str) -> List[Dict]:
        """获取新消息"""
        if self.handle and self.handle > 0:
            from wechat_decrypt_tool.wcdb_realtime import get_messages
            return get_messages(self.handle, group_id, limit=10)
        elif self.use_static_mode:
            return self._get_messages_static(group_id, limit=10)
        else:
            return []

    def _output_new_messages(self, messages: List[Dict], group_name: str,
                              group_id: str, storage, old_last_time: int,
                              saved_count: int) -> int:
        """输出新消息"""
        time_str = format_timestamp(
            max(self._get_msg_timestamp(m) for m in messages),
            '%Y-%m-%d %H:%M:%S'
        )
        print(f"\n[新消息] {time_str}", flush=True)

        for msg in reversed(messages):
            msg_time_int = self._get_msg_timestamp(msg)

            if msg_time_int > old_last_time:
                processed = self._process_single_message(msg, group_name, group_id)
                if not processed:
                    continue

                # 显示消息
                try:
                    from stock_analysis.dashboard import get_output_lock
                    with get_output_lock():
                        print(f"  [{processed['time_str']}] {processed['sender']}: {processed['content']}", flush=True)
                        print()
                except ImportError:
                    print(f"  [{processed['time_str']}] {processed['sender']}: {processed['content']}", flush=True)
                    print()

                # 保存到数据库
                if self._save_message_to_storage(processed, storage):
                    saved_count += 1
                    self._trigger_dashboard_refresh()

        return saved_count

    def _trigger_dashboard_refresh(self):
        """触发看板刷新"""
        try:
            from stock_analysis.dashboard import get_dashboard
            dashboard = get_dashboard()
            if dashboard and hasattr(dashboard, 'trigger_refresh'):
                dashboard.trigger_refresh()
        except Exception:
            pass

    def _list_message_dbs(self) -> List[str]:
        """列出所有消息数据库路径
        
        Returns:
            消息数据库路径列表
        """
        session_db_path = self._find_session_db()
        if not session_db_path:
            return []
        
        db_storage_dir = os.path.dirname(os.path.dirname(session_db_path))
        message_dir = os.path.join(db_storage_dir, "message")
        
        if not os.path.exists(message_dir):
            return []
        
        message_dbs = [
            os.path.join(message_dir, f)
            for f in os.listdir(message_dir)
            if f.endswith(".db") and not f.endswith("-shm") and not f.endswith("-wal")
            and "message" in f.lower()
        ]
        message_dbs.sort(key=lambda x: (0 if "message_0" in x else 1, x))
        
        return message_dbs

    def _find_message_db_by_table(self, target_table: str, skip_decrypt: bool = False, 
                                   message_dir: Optional[str] = None) -> Optional[str]:
        """遍历消息数据库查找包含指定表的数据库
        
        Args:
            target_table: 目标表名（如 Msg_xxx）
            skip_decrypt: 是否跳过解密（直接查找明文数据库，用于测试）
            message_dir: 可选的消息数据库目录路径（用于测试）
            
        Returns:
            找到的数据库路径，未找到返回 None
        """
        # 获取消息数据库列表
        if message_dir:
            # 使用指定的目录
            if not os.path.exists(message_dir):
                return None
            message_dbs = [
                os.path.join(message_dir, f)
                for f in os.listdir(message_dir)
                if f.endswith(".db") and not f.endswith("-shm") and not f.endswith("-wal")
            ]
        else:
            message_dbs = self._list_message_dbs()
        
        if not message_dbs:
            return None
        
        # 如果跳过解密，直接在明文数据库中查找
        if skip_decrypt:
            for db_path in message_dbs:
                try:
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND lower(name)=lower(?)",
                        (target_table,)
                    )
                    if cursor.fetchone():
                        conn.close()
                        logger.info(f"[表定位] 找到表 {target_table} 在 {db_path}")
                        return db_path
                    conn.close()
                except Exception as e:
                    logger.debug(f"[表定位] 检查 {db_path} 失败: {e}")
            logger.debug(f"[表定位] 未找到表 {target_table}")
            return None
        
        # 需要解密的常规流程
        if not self.db_key or not self.temp_dir:
            return None
        
        from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor
        decryptor = WeChatDatabaseDecryptor(self.db_key)
        
        for db_path in message_dbs:
            temp_db = os.path.join(self.temp_dir, f"temp_find_{os.path.basename(db_path)}")
            
            try:
                if not decryptor.decrypt_database(db_path, temp_db):
                    continue
                
                conn = sqlite3.connect(temp_db)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND lower(name)=lower(?)",
                    (target_table,)
                )
                
                if cursor.fetchone():
                    conn.close()
                    logger.info(f"[表定位] 找到表 {target_table} 在 {db_path}")
                    return db_path
                
                conn.close()
                
            except Exception as e:
                logger.debug(f"[表定位] 检查 {db_path} 失败: {e}")
            finally:
                try:
                    if os.path.exists(temp_db):
                        os.remove(temp_db)
                except OSError:
                    pass
        
        logger.debug(f"[表定位] 未找到表 {target_table}")
        return None

    def _build_group_db_mapping(self) -> Dict[str, str]:
        """构建群ID到数据库路径的映射缓存
        
        通过 SessionTable 正查方式：
        1. 查询 SessionTable 获取所有群 ID
        2. 对每个群 ID 计算 Msg_<MD5> 表名
        3. 遍历消息数据库查找对应的表
        
        Returns:
            群ID到数据库路径的映射字典
        """
        if not self.decrypted_session_db or not os.path.exists(self.decrypted_session_db):
            logger.warning("[映射缓存] session.db 未解密或不存在")
            return {}
        
        mapping = {}
        
        try:
            # 1. 从 SessionTable 获取所有群 ID
            conn = sqlite3.connect(self.decrypted_session_db)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT username FROM SessionTable WHERE username LIKE '%@chatroom'"
            )
            group_ids = [row[0] for row in cursor.fetchall()]
            conn.close()
            
            logger.info(f"[映射缓存] SessionTable 中发现 {len(group_ids)} 个群")
            
            # 2. 对每个群 ID 查找对应的消息数据库
            for gid in group_ids:
                expected_table = f"Msg_{hashlib.md5(gid.encode('utf-8')).hexdigest()}"
                db_path = self._find_message_db_by_table(expected_table)
                
                if db_path:
                    mapping[gid] = db_path
                    logger.debug(f"[映射缓存] 发现群: {gid} -> {db_path}")
            
            # 更新缓存
            self._group_db_mapping = mapping
            logger.info(f"[映射缓存] 共发现 {len(mapping)} 个群映射")
            
        except Exception as e:
            logger.warning(f"[映射缓存] 构建映射失败: {e}")
        
        return mapping

    def _get_messages_static(self, group_id: str, limit: int = 30) -> List[Dict]:
        """使用静态解密方式获取消息 - 新流程：遍历所有分片 → 全部收集 → 全局排序 → 截取最新"""
        from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor

        logger.info(f"[消息查询] 开始查询群聊消息, group_id={group_id}, limit={limit}")

        if not self.db_key or not self.temp_dir:
            logger.warning("[消息查询] 密钥或临时目录未初始化")
            return []

        # 计算消息表名
        expected_table = f"Msg_{hashlib.md5(group_id.encode('utf-8')).hexdigest()}"
        logger.debug(f"[消息查询] 期望表名: {expected_table}")

        # 查找 message 目录
        session_db_path = self._find_session_db()
        if not session_db_path:
            logger.warning("[消息查询] session.db 路径未找到")
            return []

        db_storage_dir = os.path.dirname(os.path.dirname(session_db_path))
        message_dir = os.path.join(db_storage_dir, "message")

        if not os.path.exists(message_dir):
            logger.warning(f"[消息查询] 消息目录不存在: {message_dir}")
            return []

        # 获取所有消息数据库文件
        message_dbs = [
            f for f in os.listdir(message_dir)
            if f.endswith(".db") and not f.endswith("-shm") and not f.endswith("-wal")
            and "message" in f.lower()
        ]
        message_dbs.sort(key=lambda x: (0 if x.startswith("message_") else 1, x))

        logger.info(f"[消息查询] 找到 {len(message_dbs)} 个消息数据库，开始遍历所有分片")

        decryptor = WeChatDatabaseDecryptor(self.db_key)
        all_messages = []

        # 必须遍历所有分片，全部收集消息，不提前终止
        for db_name in message_dbs:
            db_path = os.path.join(message_dir, db_name)
            temp_db = os.path.join(self.temp_dir, f"temp_{db_name}")

            try:
                if not decryptor.decrypt_database(db_path, temp_db):
                    continue

                messages = self._query_messages_from_db(temp_db, expected_table)
                if messages:
                    all_messages.extend(messages)
                # 继续遍历下一个分片，不提前终止

            except Exception as e:
                logger.warning(f"[消息查询] 处理 {db_name} 失败: {e}")
            finally:
                # 清理临时文件
                try:
                    if os.path.exists(temp_db):
                        os.remove(temp_db)
                except OSError:
                    pass

        # 全局排序：按时间从小到大，最新消息在最后
        all_messages.sort(key=lambda x: int(x.get('create_time') or 0))
        # 截取最新的 limit 条消息
        if len(all_messages) > limit:
            result = all_messages[-limit:]
            logger.info(f"[消息查询] 遍历完成，共收集 {len(all_messages)} 条，截取最新 {len(result)} 条")
            return result
        logger.info(f"[消息查询] 遍历完成，共收集 {len(all_messages)} 条消息")
        return all_messages

    def _query_messages_from_db(self, db_path: str, expected_table: str) -> List[Dict]:
        """从解密后的数据库查询消息 - 查询该分片所有消息，不做 limit 限制"""
        messages = []
        
        try:
            with sqlite3.connect(db_path) as conn:
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
                    return messages

                actual_table = row[0]
                logger.debug(f"[消息查询] 找到表: {actual_table}")

                # 检查表字段
                cursor.execute(f"PRAGMA table_info({actual_table})")
                columns = [col[1] for col in cursor.fetchall()]

                # 动态构建查询（根据是否有 compress_content 字段）
                content_col = "m.compress_content, m.message_content" if 'compress_content' in columns else "m.message_content"
                cursor.execute(f"""
                    SELECT m.local_id, m.create_time, {content_col}, m.real_sender_id,
                           COALESCE(n.user_name, '') as sender_username
                    FROM {actual_table} m
                    LEFT JOIN Name2Id n ON m.real_sender_id = n.rowid
                    ORDER BY m.create_time DESC
                """)

                for row in cursor.fetchall():
                    try:
                        content = self._decode_db_message_content(row, columns)
                        sender_username = row['sender_username'] if 'sender_username' in row.keys() else ''
                        if not sender_username:
                            sender_username = str(row['real_sender_id']) if row['real_sender_id'] else '未知'

                        messages.append({
                            'local_id': row['local_id'],
                            'create_time': row['create_time'] or 0,
                            'message_content': content or '',
                            'sender_username': sender_username
                        })
                    except Exception as e:
                        logger.warning(f"[消息查询] 解析消息失败: {e}")

        except sqlite3.Error as e:
            logger.warning(f"[消息查询] 数据库查询失败: {e}")

        return messages

    def _decode_db_message_content(self, row: sqlite3.Row, columns: List[str]) -> str:
        """解码数据库中的消息内容"""
        content = row['message_content']
        compress = row['compress_content'] if 'compress_content' in columns else None

        # 优先使用 compress_content
        if compress and isinstance(compress, bytes):
            decompressed = self._decompress_zstd_data(compress)
            if decompressed is not None:
                return decompressed
            return compress.decode('utf-8', errors='replace')
        elif isinstance(content, bytes):
            decompressed = self._decompress_zstd_data(content)
            if decompressed is not None:
                return decompressed
            try:
                return content.decode('utf-8', errors='replace')
            except Exception:
                return str(content)

        return content or ''

    def run(self):
        """运行主流程"""
        self.print_header()

        try:
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

        finally:
            # 清理密钥文件
            self._cleanup_key_file()

    def _cleanup_key_file(self):
        """清理密钥文件"""
        try:
            exe_dir = get_exe_dir()
            key_store_path = exe_dir / 'output' / 'account_keys.json'
            if key_store_path.exists():
                key_store_path.unlink()
                logger.info("[清理] 已清除密钥文件")
        except OSError as e:
            logger.warning(f"[清理] 清除密钥文件失败: {e}")


# ==================== 主函数 ====================

def main():
    """主函数 - 生产版本（带全局异常处理）"""
    try:
        monitor = SimpleMonitor()
        monitor.run()
    except KeyboardInterrupt:
        print('\n\n[用户中断]')
        sys.exit(0)
    except Exception as e:
        # 记录异常到日志
        logger.exception(f"程序发生未捕获异常: {e}")
        
        # 显示错误并退出
        display_error_and_exit(e)


if __name__ == '__main__':
    main()