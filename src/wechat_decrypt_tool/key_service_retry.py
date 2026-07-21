#!/usr/bin/env python3
"""
密钥获取服务（带重试机制）
==========================

功能:
- 整合多种密钥获取方式
- 自动重试机制
- 优先使用已存储的密钥
- 支持 V4 版本微信

用于解决干净环境下首次登录时密钥获取失败的问题。
"""

import time
from pathlib import Path
from typing import Optional, Tuple

from .key_store import load_account_keys_store, upsert_account_keys_in_store
from .dll_key_scan import extract_xor_keys_from_dll


class KeyAcquisitionService:
    """密钥获取服务类"""

    def __init__(
        self,
        max_retries: int = 3,
        retry_interval: float = 3.0,
        verbose: bool = True
    ):
        """
        Args:
            max_retries: 最大重试次数
            retry_interval: 重试间隔（秒）
            verbose: 是否显示进度
        """
        self.max_retries = max_retries
        self.retry_interval = retry_interval
        self.verbose = verbose

    def _log(self, message: str):
        """打印日志"""
        if self.verbose:
            print(message)

    def get_stored_key(self, account_id: str) -> Optional[str]:
        """
        获取已存储的密钥

        Args:
            account_id: 微信账号 ID

        Returns:
            密钥字符串，不存在返回 None
        """
        store = load_account_keys_store()
        accounts = store.get('accounts', {})

        if account_id in accounts:
            key = accounts[account_id].get('db_key')
            if key:
                self._log(f"[密钥] 从存储中找到密钥: {key[:16]}...")
                return key

        return None

    def get_key_from_memory(
        self,
        pid: int,
        db_file_path: str,
        internal_db_key: Optional[bytes] = None
    ) -> Optional[str]:
        """
        通过内存扫描获取密钥

        Args:
            pid: 微信进程 PID
            db_file_path: 数据库文件路径（用于验证密钥）
            internal_db_key: 内部数据库密钥（可选）

        Returns:
            密钥字符串，失败返回 None
        """
        try:
            from .key_v4 import recover_key

            self._log(f"[密钥] 正在从内存扫描密钥 (PID={pid})...")

            key = recover_key(pid, db_file_path, internal_db_key)

            if key:
                self._log(f"[密钥] 内存扫描成功: {key[:16]}...")
            else:
                self._log(f"[密钥] 内存扫描未找到密钥")

            return key

        except Exception as e:
            self._log(f"[错误] 内存扫描失败: {e}")
            return None

    def get_key_from_dll(self, dll_path: str) -> list:
        """
        通过扫描 Weixin.dll 获取内部密钥

        Args:
            dll_path: Weixin.dll 文件路径

        Returns:
            密钥候选列表
        """
        try:
            self._log(f"[密钥] 正在扫描 DLL: {dll_path}")

            results = extract_xor_keys_from_dll(dll_path)

            if results:
                self._log(f"[密钥] DLL 扫描找到 {len(results)} 个候选密钥")
            else:
                self._log(f"[密钥] DLL 扫描未找到密钥")

            return results

        except Exception as e:
            self._log(f"[错误] DLL 扫描失败: {e}")
            return []

    def acquire_key_with_retry(
        self,
        account_id: str,
        pid: int,
        db_file_path: str,
        internal_db_key: Optional[bytes] = None,
        dll_path: Optional[str] = None,
        save_on_success: bool = True
    ) -> Tuple[bool, Optional[str]]:
        """
        带重试机制的密钥获取

        尝试顺序:
        1. 已存储的密钥
        2. 内存扫描（带重试）
        3. DLL 扫描（如果提供）

        Args:
            account_id: 微信账号 ID
            pid: 微信进程 PID
            db_file_path: 数据库文件路径
            internal_db_key: 内部数据库密钥
            dll_path: Weixin.dll 路径
            save_on_success: 成功后是否保存

        Returns:
            (是否成功, 密钥字符串)
        """
        # 优先级1: 检查已存储的密钥
        stored_key = self.get_stored_key(account_id)
        if stored_key:
            self._log(f"[密钥] 使用已存储的密钥")
            return True, stored_key

        self._log(f"\n[密钥获取] 开始获取密钥...")
        self._log(f"  - 账号: {account_id}")
        self._log(f"  - PID: {pid}")
        self._log(f"  - 最大重试: {self.max_retries} 次")
        self._log(f"  - 重试间隔: {self.retry_interval} 秒")

        # 优先级2: 内存扫描（带重试）
        for attempt in range(1, self.max_retries + 1):
            self._log(f"\n[密钥] 第 {attempt}/{self.max_retries} 次尝试...")

            key = self.get_key_from_memory(pid, db_file_path, internal_db_key)

            if key:
                if save_on_success:
                    self.save_key(account_id, key)
                return True, key

            if attempt < self.max_retries:
                self._log(f"[密钥] 等待 {self.retry_interval} 秒后重试...")
                time.sleep(self.retry_interval)

        # 优先级3: DLL 扫描（如果提供）
        if dll_path and Path(dll_path).exists():
            self._log(f"\n[密钥] 尝试 DLL 扫描...")
            dll_results = self.get_key_from_dll(dll_path)

            if dll_results:
                # 尝试验证每个候选
                for result in dll_results:
                    key_hex = result.get('key_hex', '')
                    if key_hex:
                        # 注意：DLL 扫描的是 internal_db_key，不是最终的 db_key
                        # 这里只是记录，实际使用需要配合其他方式验证
                        self._log(f"[密钥] DLL 候选: {key_hex[:16]}...")

        self._log(f"\n[失败] 密钥获取失败，已重试 {self.max_retries} 次")
        return False, None

    def save_key(self, account_id: str, key: str, **kwargs):
        """
        保存密钥到存储

        Args:
            account_id: 微信账号 ID
            key: 密钥字符串
            **kwargs: 其他参数（如 data_path）
        """
        try:
            upsert_account_keys_in_store(account_id, db_key=key, **kwargs)
            self._log(f"[密钥] 已保存到密钥存储")
        except Exception as e:
            self._log(f"[警告] 密钥保存失败: {e}")


def acquire_wechat_key(
    account_id: str,
    pid: int,
    db_file_path: str,
    max_retries: int = 3,
    retry_interval: float = 3.0,
    internal_db_key: Optional[bytes] = None,
    dll_path: Optional[str] = None,
    verbose: bool = True
) -> Tuple[bool, Optional[str]]:
    """
    便捷函数：获取微信密钥

    Args:
        account_id: 微信账号 ID
        pid: 微信进程 PID
        db_file_path: 数据库文件路径
        max_retries: 最大重试次数
        retry_interval: 重试间隔
        internal_db_key: 内部数据库密钥
        dll_path: Weixin.dll 路径
        verbose: 是否显示进度

    Returns:
        (是否成功, 密钥字符串)
    """
    service = KeyAcquisitionService(
        max_retries=max_retries,
        retry_interval=retry_interval,
        verbose=verbose
    )

    return service.acquire_key_with_retry(
        account_id=account_id,
        pid=pid,
        db_file_path=db_file_path,
        internal_db_key=internal_db_key,
        dll_path=dll_path
    )