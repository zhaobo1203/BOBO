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
from pathlib import Path
from datetime import datetime

# Windows PyInstaller 打包必须：防止 multiprocessing 子进程重新执行主程序
# 必须在程序最开始时调用，否则会导致程序卡死
multiprocessing.freeze_support()

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
            # 账号检测失败时，尝试在检测到的目录中查找包含有效数据库的账号目录
            self.data_path = self._find_any_valid_account_dir(detected_dirs)
            if self.data_path:
                # 从路径中提取账号ID
                dir_name = Path(self.data_path).name
                if dir_name.startswith('wxid_') or dir_name.startswith('wl_'):
                    self.account_id = dir_name
                self.print_step("账号识别", "done", f"自动发现: {self.account_id or '未知账号'}")
                logger.info(f"[步骤2] 自动发现账号目录: {self.data_path}")
                return True
            else:
                # 最后降级：使用第一个检测到的目录
                self.data_path = detected_dirs[0]
                self.print_step("账号识别", "done", "使用默认目录")
                logger.warning(f"[步骤2] 未能找到有效账号目录，使用默认: {self.data_path}")
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

    def _find_any_valid_account_dir(self, base_dirs: list) -> str | None:
        """在检测到的目录中查找包含有效数据库的账号目录
        
        当账号检测失败时，遍历检测到的目录，找到包含有效 db_storage 的账号子目录。
        """
        for base_dir in base_dirs:
            base_path = Path(base_dir)
            if not base_path.exists() or not base_path.is_dir():
                continue
            
            logger.debug(f"[账号查找] 遍历目录: {base_dir}")
            
            try:
                # 遍历子目录，查找 wxid_* 或 wl_* 开头的账号目录
                for sub_dir in base_path.iterdir():
                    if not sub_dir.is_dir():
                        continue
                    
                    # 跳过非账号目录
                    dir_name = sub_dir.name.lower()
                    if dir_name in ['all users', 'applet', 'wmpf', 'backup', 'config']:
                        continue
                    
                    # 检查是否包含有效的 session.db
                    session_db = sub_dir / 'db_storage' / 'session' / 'session.db'
                    if session_db.exists():
                        logger.info(f"[账号查找] 找到有效账号目录: {sub_dir}")
                        return str(sub_dir)
                    
                    # 也检查旧版路径
                    session_db_alt = sub_dir / 'db_storage' / 'session.db'
                    if session_db_alt.exists():
                        logger.info(f"[账号查找] 找到有效账号目录(旧版路径): {sub_dir}")
                        return str(sub_dir)
                        
            except (PermissionError, OSError) as e:
                logger.debug(f"[账号查找] 遍历目录失败: {base_dir}, 错误: {e}")
                continue
            
            # 检查 "WeChat Files" 子目录结构
            wechat_files_path = base_path / 'WeChat Files'
            if wechat_files_path.exists() and wechat_files_path.is_dir():
                try:
                    for sub_dir in wechat_files_path.iterdir():
                        if not sub_dir.is_dir():
                            continue
                        
                        dir_name = sub_dir.name.lower()
                        if dir_name in ['all users', 'applet', 'wmpf', 'backup']:
                            continue
                        
                        session_db = sub_dir / 'db_storage' / 'session' / 'session.db'
                        if session_db.exists():
                            logger.info(f"[账号查找] 找到有效账号目录(WeChat Files): {sub_dir}")
                            return str(sub_dir)
                            
                except (PermissionError, OSError) as e:
                    logger.debug(f"[账号查找] 遍历WeChat Files目录失败: {e}")
                    continue
        
        logger.warning("[账号查找] 未找到任何有效的账号目录")
        return None

    def step3_get_key(self):
        """步骤3: 密钥获取 - 每次启动重新获取，不使用旧密钥"""
        self.print_step("密钥获取", "doing")

        import json
        import traceback

        exe_dir = get_exe_dir()
        cwd = Path.cwd()

        # 清除旧的密钥文件，确保每次启动都重新获取
        key_store_path = exe_dir / 'output' / 'account_keys.json'
        if key_store_path.exists():
            try:
                key_store_path.unlink()
                logger.info("[步骤3] 已清除旧密钥文件，将重新获取")
                print("    检查旧密钥文件: 已清除，将重新获取")
            except Exception as e:
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

                    # 验证密钥是否匹配session.db
                    print(f"  验证密钥与数据库匹配性...", flush=True)
                    logger.info("[步骤3] 开始验证密钥与数据库匹配性")

                    if self._verify_key_and_find_matching_db():
                        self.print_step("密钥获取", "done", "Hook注入成功")
                        logger.info("[步骤3] Hook注入成功获取密钥（已验证匹配）")
                        self._save_key()
                        return True
                    else:
                        # 密钥不匹配任何session.db，但仍保存密钥，让步骤4尝试
                        logger.warning("[步骤3] 密钥与所有session.db不匹配，将继续尝试")
                        print(f"  [!] 密钥与当前数据库不匹配，将在步骤4中重试")
                        self.print_step("密钥获取", "done", "Hook注入成功（未验证）")
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

        # 方法3: 所有方式都失败，提供手动输入降级
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

    def _prompt_manual_key(self) -> str | None:
        """提示用户手动输入64位十六进制密钥（超时降级）"""
        import re
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

        try:
            PAGE_SIZE = 4096
            SALT_SIZE = 16
            IV_SIZE = 16
            HMAC_SIZE = 64
            RESERVE_SIZE = IV_SIZE + HMAC_SIZE
            KEY_SIZE = 32

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

            # 将hex密钥转为bytes
            key_bytes = bytes.fromhex(db_key)

            # 尝试两种模式：raw enc_key 和 passphrase
            # 模式1: key是raw enc_key
            enc_key_1 = key_bytes
            mac_key_1 = hashlib.pbkdf2_hmac("sha512", enc_key_1, bytes(b ^ 0x3A for b in salt), 2, dklen=KEY_SIZE)

            # 模式2: key是passphrase，需要先derive
            enc_key_2 = hashlib.pbkdf2_hmac("sha512", key_bytes, salt, 256000, dklen=KEY_SIZE)
            mac_key_2 = hashlib.pbkdf2_hmac("sha512", enc_key_2, bytes(b ^ 0x3A for b in salt), 2, dklen=KEY_SIZE)

            # 计算Page1的HMAC
            stored_hmac = page1[PAGE_SIZE - HMAC_SIZE: PAGE_SIZE]

            for mode, mac_key in [("raw_key", mac_key_1), ("passphrase", mac_key_2)]:
                # 计算期望的HMAC
                offset = SALT_SIZE  # page1从salt后开始
                data_end = PAGE_SIZE - RESERVE_SIZE + IV_SIZE
                mac = hmac_mod.new(mac_key, digestmod=hashlib.sha512)
                mac.update(page1[offset:data_end])
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

    def _find_all_session_dbs(self) -> list[str]:
        """查找所有可能的session.db路径

        使用 rglob 递归搜索所有微信数据目录，覆盖各种目录结构：
        - xwechat_files/<account>_<suffix>/db_storage/session/session.db
        - xwechat_files/all_users/login/<account>/...
        - Weixin/xwechat_files/...
        - 任意嵌套结构

        Returns:
            session.db路径列表
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
                    # 只保留在 db_storage 或 session 目录下的 session.db
                    path_str = str(item).lower()
                    if 'db_storage' in path_str or 'session' in str(item.parent).lower():
                        _add_if_new(item)
            except (PermissionError, OSError) as e:
                logger.debug(f"[session.db搜索] rglob搜索失败: {base_dir}, 错误: {e}")

        # 1. 当前data_path下的session.db（直接路径，优先）
        if self.data_path:
            data_path_obj = Path(self.data_path)
            _add_if_new(data_path_obj / 'db_storage' / 'session' / 'session.db')
            _add_if_new(data_path_obj / 'db_storage' / 'session.db')

        # 2. 搜索所有微信数据目录（递归）
        try:
            detection = detect_wechat_installation()
            wechat_data_dirs = detection.get('data_dirs', [])

            for data_dir in wechat_data_dirs:
                data_dir_obj = Path(data_dir)
                if not data_dir_obj.exists():
                    continue

                # 递归搜索整个数据目录下的 session.db
                _rglob_session_dbs(data_dir_obj)

        except Exception as e:
            logger.warning(f"[session.db搜索] 搜索微信数据目录失败: {e}")

        logger.info(f"[session.db搜索] 找到 {len(all_paths)} 个session.db路径")
        for p in all_paths:
            logger.debug(f"[session.db搜索]   - {p}")
        return all_paths

    def _verify_key_and_find_matching_db(self) -> bool:
        """验证密钥是否匹配当前session.db，不匹配则搜索其他路径

        包含等待重试机制：Hook获取密钥后，微信可能需要几秒才能用新密钥更新session.db

        Returns:
            True=找到匹配的数据库, False=未找到
        """
        if not self.db_key:
            return False

        session_db_path = self._find_session_db()
        if not session_db_path:
            logger.warning("[密钥验证] 未找到session.db")
            return False

        # 验证当前session.db
        if self._verify_key_matches_db(session_db_path, self.db_key):
            logger.info("[密钥验证] 密钥匹配当前session.db")
            return True

        logger.warning(f"[密钥验证] 密钥不匹配当前session.db: {session_db_path}")
        print(f"  [!] 密钥与当前session.db不匹配，搜索其他数据目录...")

        # 搜索所有session.db，找到密钥匹配的
        all_session_dbs = self._find_all_session_dbs()
        for db_path in all_session_dbs:
            if db_path == session_db_path:
                continue  # 已经验证过
            logger.info(f"[密钥验证] 尝试: {db_path}")
            if self._verify_key_matches_db(db_path, self.db_key):
                logger.info(f"[密钥验证] 找到匹配的session.db: {db_path}")
                print(f"  [OK] 找到密钥匹配的数据库: {db_path}")

                # 更新data_path为匹配的数据库所在目录
                # db_path: .../ToweR1989_b2c9/db_storage/session/session.db
                # data_path应为: .../ToweR1989_b2c9
                new_data_path = str(Path(db_path).parent.parent.parent)
                if Path(new_data_path).exists():
                    logger.info(f"[密钥验证] 更新data_path: {self.data_path} -> {new_data_path}")
                    self.data_path = new_data_path
                    return True

        # 所有session.db都不匹配，尝试等待重试
        # Hook获取密钥后，微信可能需要几秒才能用新密钥更新session.db
        logger.info("[密钥验证] 首次验证失败，等待5秒后重试...")
        print(f"  等待微信更新数据库（5秒）...", flush=True)
        time.sleep(5)

        # 重新验证当前session.db
        session_db_path = self._find_session_db()
        if session_db_path and self._verify_key_matches_db(session_db_path, self.db_key):
            logger.info("[密钥验证] 重试验证成功")
            return True

        # 重新搜索所有session.db
        all_session_dbs = self._find_all_session_dbs()
        for db_path in all_session_dbs:
            if self._verify_key_matches_db(db_path, self.db_key):
                logger.info(f"[密钥验证] 重试找到匹配的session.db: {db_path}")
                print(f"  [OK] 重试找到密钥匹配的数据库: {db_path}")
                new_data_path = str(Path(db_path).parent.parent.parent)
                if Path(new_data_path).exists():
                    logger.info(f"[密钥验证] 更新data_path: {self.data_path} -> {new_data_path}")
                    self.data_path = new_data_path
                    return True

        logger.warning("[密钥验证] 所有session.db均不匹配当前密钥")
        print(f"  [!] 未找到密钥匹配的数据库")
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

        # 在解密前再次验证密钥与数据库匹配性
        # （步骤3可能验证未通过，此时微信已完全初始化，数据库可能已更新）
        session_db_path = self._find_session_db()
        if not session_db_path:
            self.print_step("数据库连接", "fail", "session.db不存在")
            return False

        # 验证密钥是否匹配当前session.db
        if not self._verify_key_matches_db(session_db_path, self.db_key):
            logger.warning("[步骤4] 密钥与当前session.db不匹配，重新搜索匹配的数据库...")
            print(f"  [!] 密钥与session.db不匹配，重新搜索...")

            if self._verify_key_and_find_matching_db():
                # 找到了匹配的数据库，重新获取session.db路径
                session_db_path = self._find_session_db()
                if not session_db_path:
                    self.print_step("数据库连接", "fail", "session.db不存在")
                    return False
                logger.info(f"[步骤4] 密钥验证通过，使用匹配的数据库: {session_db_path}")
            else:
                # 所有session.db都不匹配，仍然尝试解密（可能数据库刚被微信更新）
                logger.warning("[步骤4] 所有session.db均不匹配密钥，仍将尝试解密")
                print(f"  [!] 未找到密钥匹配的数据库，仍将尝试解密...")

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
        """查找session.db路径
        
        支持两种情况：
        1. data_path 已经是账号目录（包含 db_storage）
        2. data_path 是微信数据根目录（包含 wxid_* 子目录）
        """
        if not self.data_path:
            logger.warning("[session.db查找] data_path 未设置")
            return None

        data_path_obj = Path(self.data_path)
        if not data_path_obj.exists():
            logger.warning(f"[session.db查找] 路径不存在: {self.data_path}")
            return None

        # 优先检查：data_path 已经是账号目录
        direct_paths = [
            data_path_obj / 'db_storage' / 'session' / 'session.db',
            data_path_obj / 'db_storage' / 'session.db',
            data_path_obj / 'session.db',
        ]
        
        for path in direct_paths:
            logger.debug(f"[session.db查找] 检查直接路径: {path}")
            if path.exists():
                logger.info(f"[session.db查找] 找到: {path}")
                return str(path)

        # 如果直接路径不存在，检查是否是根目录（包含账号子目录）
        logger.debug(f"[session.db查找] 直接路径不存在，检查子目录...")
        
        try:
            for item in data_path_obj.iterdir():
                if not item.is_dir():
                    continue
                
                # 跳过非账号目录
                dir_name = item.name.lower()
                if dir_name in ['all users', 'applet', 'wmpf', 'backup', 'config', 'cache']:
                    continue
                
                # 检查账号子目录中的 session.db
                session_db = item / 'db_storage' / 'session' / 'session.db'
                logger.debug(f"[session.db查找] 检查子目录: {session_db}")
                if session_db.exists():
                    logger.info(f"[session.db查找] 在子目录找到: {session_db}")
                    return str(session_db)
                
                # 也检查旧版路径
                session_db_alt = item / 'db_storage' / 'session.db'
                if session_db_alt.exists():
                    logger.info(f"[session.db查找] 在子目录找到(旧版): {session_db_alt}")
                    return str(session_db_alt)
                    
        except (PermissionError, OSError) as e:
            logger.warning(f"[session.db查找] 遍历目录失败: {e}")

        # 检查 "WeChat Files" 子目录结构
        wechat_files_path = data_path_obj / 'WeChat Files'
        if wechat_files_path.exists() and wechat_files_path.is_dir():
            logger.debug(f"[session.db查找] 检查 WeChat Files 子目录...")
            try:
                for item in wechat_files_path.iterdir():
                    if not item.is_dir():
                        continue
                    
                    dir_name = item.name.lower()
                    if dir_name in ['all users', 'applet', 'wmpf', 'backup']:
                        continue
                    
                    session_db = item / 'db_storage' / 'session' / 'session.db'
                    if session_db.exists():
                        logger.info(f"[session.db查找] 在 WeChat Files 找到: {session_db}")
                        return str(session_db)
                        
            except (PermissionError, OSError) as e:
                logger.warning(f"[session.db查找] 遍历 WeChat Files 失败: {e}")

        logger.warning(f"[session.db查找] 未找到 session.db，搜索路径: {self.data_path}")
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
                messages = get_messages(self.handle, group_id, limit=100)
                if messages:
                    print(f"  [OK] 使用 WCDB 获取到 {len(messages)} 条历史消息")
            except Exception as e:
                logger.warning(f"[监控] WCDB 获取消息失败: {e}")

        # 如果 WCDB 失败，尝试静态解密
        if not messages and getattr(self, 'use_static_mode', False):
            print("  [..] WCDB 方式失败，尝试静态解密...")
            messages = self._get_messages_static(group_id, limit=100)

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

                time_str = datetime.fromtimestamp(msg_time_int).strftime('%H:%M:%S') if msg_time_int else "--:--:--"
                print(f"    [{time_str}] {sender}: {content}")
                print()  # 消息之间空一行

            print()

            # 保存历史消息到数据库
            history_saved = 0
            for msg in messages:
                msg_time = msg.get('create_time') or msg.get('createTime') or 0
                try:
                    msg_time_int = int(msg_time) if msg_time else 0
                except:
                    msg_time_int = 0

                sender_wxid = msg.get('sender_username') or msg.get('sender') or '未知'
                sender = self._get_display_name(sender_wxid)
                raw_content = msg.get('message_content') or msg.get('content') or ''
                content = self.decode_message(raw_content)

                if self._is_non_text_message(content):
                    continue
                content = self._clean_message_content(content)
                if len(content.strip()) < 1:
                    continue

                try:
                    storage.save_message(
                        sender_nickname=sender,
                        message_content=content,
                        send_time=datetime.fromtimestamp(msg_time_int),
                        group_name=group_name,
                        group_id=group_id,
                        sender_id=sender_wxid
                    )
                    history_saved += 1
                except Exception as e:
                    logger.warning(f"[监控] 保存历史消息失败: {e}")

            if history_saved > 0:
                print(f"  [OK] 已保存 {history_saved} 条历史消息到数据库")
                # 触发看板刷新，让股票分析尽快处理历史消息
                try:
                    from stock_analysis.dashboard import get_dashboard
                    dashboard = get_dashboard()
                    if dashboard:
                        dashboard.trigger_refresh()
                except Exception:
                    pass
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
                            # 显示完整消息内容（使用输出锁防止与看板刷新冲突）
                            try:
                                from stock_analysis.dashboard import get_output_lock
                                with get_output_lock():
                                    print(f"  [{time_str}] {sender}: {content}", flush=True)
                                    print()  # 消息之间空一行
                            except ImportError:
                                print(f"  [{time_str}] {sender}: {content}", flush=True)
                                print()

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
                                # 通知看板刷新（增量匹配+重新渲染）
                                try:
                                    from stock_analysis.dashboard import get_dashboard
                                    _dash = get_dashboard()
                                    if _dash and hasattr(_dash, 'trigger_refresh'):
                                        _dash.trigger_refresh()
                                except Exception:
                                    pass
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

                # 触发看板刷新（通知dashboard线程重新渲染）
                try:
                    from stock_analysis.dashboard import get_dashboard
                    dashboard = get_dashboard()
                    if dashboard and hasattr(dashboard, 'trigger_refresh'):
                        dashboard.trigger_refresh()
                except Exception:
                    pass  # 看板刷新失败不影响主流程

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

                # 查询消息 - 使用 LEFT JOIN Name2Id 将 real_sender_id 映射到 user_name
                # 根据字段选择查询语句
                if 'compress_content' in columns:
                    cursor.execute(f"""
                        SELECT m.local_id, m.create_time, m.message_content, m.compress_content, m.real_sender_id,
                               COALESCE(n.user_name, '') as sender_username
                        FROM {actual_table} m
                        LEFT JOIN Name2Id n ON m.real_sender_id = n.rowid
                        ORDER BY m.create_time DESC
                        LIMIT ?
                    """, (limit,))
                else:
                    cursor.execute(f"""
                        SELECT m.local_id, m.create_time, m.message_content, m.real_sender_id,
                               COALESCE(n.user_name, '') as sender_username
                        FROM {actual_table} m
                        LEFT JOIN Name2Id n ON m.real_sender_id = n.rowid
                        ORDER BY m.create_time DESC
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

                        # 获取发送者 - 优先使用 JOIN 得到的 sender_username
                        sender_username = row['sender_username'] if 'sender_username' in row.keys() else ''
                        if not sender_username:
                            # 如果 JOIN 失败，使用原始的 real_sender_id
                            sender_username = str(row['real_sender_id']) if row['real_sender_id'] else '未知'

                        messages.append({
                            'local_id': row['local_id'],
                            'create_time': row['create_time'] or 0,
                            'message_content': content or '',
                            'sender_username': sender_username
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


def _get_log_file_path() -> Path | None:
    """获取最新的日志文件路径"""
    exe_dir = get_exe_dir()
    log_dir = exe_dir / 'logs'
    
    if not log_dir.exists():
        log_dir = Path.cwd() / 'logs'
    
    if not log_dir.exists():
        return None
    
    # 查找最新的日志文件
    log_files = list(log_dir.glob('app_*.log'))
    if log_files:
        return max(log_files, key=lambda f: f.stat().st_mtime)
    
    log_files = list(log_dir.glob('*.log'))
    if log_files:
        return max(log_files, key=lambda f: f.stat().st_mtime)
    
    return None


def _open_log_file():
    """打开日志文件"""
    log_path = _get_log_file_path()
    if log_path and log_path.exists():
        import subprocess
        try:
            if sys.platform == 'win32':
                os.startfile(str(log_path))
            else:
                subprocess.run(['open', str(log_path)] if sys.platform == 'darwin' else ['xdg-open', str(log_path)])
            print(f"\n  已打开日志文件: {log_path.name}")
        except Exception as e:
            print(f"\n  无法打开日志文件: {e}")
            print(f"  日志路径: {log_path}")
    else:
        print("\n  未找到日志文件")


def _cleanup_key_file():
    """清理密钥文件 - 程序退出时调用"""
    try:
        exe_dir = get_exe_dir()
        key_store_path = exe_dir / 'output' / 'account_keys.json'
        if key_store_path.exists():
            key_store_path.unlink()
            logger.info("[清理] 已清除密钥文件")
    except Exception as e:
        logger.warning(f"[清理] 清除密钥文件失败: {e}")


def main():
    """主函数 - 生产版本（带全局异常处理）"""
    try:
        monitor = SimpleMonitor()
        monitor.run()
        # 正常退出时清除密钥
        _cleanup_key_file()
    except KeyboardInterrupt:
        print('\n\n[用户中断]')
        _cleanup_key_file()
        sys.exit(0)
    except Exception as e:
        # 异常退出时也清除密钥
        _cleanup_key_file()
        
        # 记录异常到日志
        logger.exception(f"程序发生未捕获异常: {e}")
        
        # 显示友好的错误信息
        print()
        print("=" * 60)
        print("  程序遇到错误，抱歉!")
        print("=" * 60)
        print()
        print(f"  错误类型: {type(e).__name__}")
        print(f"  错误信息: {str(e)[:100]}")
        print()
        print("  可能的解决方案:")
        print("  1. 确保微信已登录")
        print("  2. 以管理员权限运行程序")
        print("  3. 检查杀毒软件是否拦截")
        print()
        
        # 尝试打开日志文件
        log_path = _get_log_file_path()
        if log_path:
            print(f"  日志文件: {log_path}")
            
            # 询问是否打开日志
            try:
                choice = input("\n  是否打开日志文件查看详情? (y/n): ").strip().lower()
                if choice == 'y' or choice == 'yes':
                    _open_log_file()
            except (EOFError, KeyboardInterrupt):
                pass
        
        print()
        input("  按 Enter 键退出...")
        sys.exit(1)


if __name__ == '__main__':
    main()
