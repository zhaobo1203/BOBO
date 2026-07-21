#!/usr/bin/env python3
"""
微信初始化等待器
================

功能:
- 等待微信进程完全启动
- 等待微信数据目录创建完成
- 等待关键数据库文件就绪

用于解决干净环境下首次登录时密钥获取失败的问题。
"""

import os
import time
from pathlib import Path
from typing import Optional, List

from .wechat_detection import auto_detect_wechat_data_dirs


def wait_for_wechat_process(
    process_name: str = "Weixin.exe",
    timeout: int = 60,
    interval: float = 1.0,
    verbose: bool = True
) -> Optional[int]:
    """
    等待微信进程启动

    Args:
        process_name: 进程名称 (Weixin.exe 或 WeChat.exe)
        timeout: 超时时间（秒）
        interval: 检查间隔（秒）
        verbose: 是否显示进度

    Returns:
        进程 PID，超时返回 None
    """
    from .wechat_detection import get_process_list

    start_time = time.time()
    elapsed = 0

    if verbose:
        print(f"[等待] 等待微信进程启动... (超时: {timeout}秒)")

    while elapsed < timeout:
        process_list = get_process_list()
        for pid, name in process_list:
            if name.lower() == process_name.lower():
                if verbose:
                    print(f"[OK] 检测到微信进程: {name} PID={pid}")
                return pid

        if verbose and int(elapsed) % 5 == 0 and int(elapsed) > 0:
            print(f"[等待] 已等待 {int(elapsed)} 秒...")

        time.sleep(interval)
        elapsed = time.time() - start_time

    if verbose:
        print(f"[超时] 未检测到微信进程")
    return None


def wait_for_wechat_data_dir(
    account_id: str,
    timeout: int = 60,
    interval: float = 2.0,
    verbose: bool = True
) -> Optional[Path]:
    """
    等待微信数据目录创建

    Args:
        account_id: 微信账号 ID
        timeout: 超时时间（秒）
        interval: 检查间隔（秒）

    Returns:
        数据目录路径，超时返回 None
    """
    start_time = time.time()
    elapsed = 0

    if verbose:
        print(f"[等待] 等待账号数据目录创建: {account_id}... (超时: {timeout}秒)")

    data_dirs = auto_detect_wechat_data_dirs()

    while elapsed < timeout:
        for data_dir in data_dirs:
            # 查找账号目录
            account_pattern = f"{account_id}*"
            account_dir = Path(data_dir) / account_pattern

            import glob
            matches = glob.glob(str(account_dir))
            if matches:
                db_storage = Path(matches[0]) / "db_storage"
                if db_storage.exists():
                    if verbose:
                        print(f"[OK] 检测到数据目录: {db_storage}")
                    return db_storage

        if verbose and int(elapsed) % 10 == 0 and int(elapsed) > 0:
            print(f"[等待] 已等待 {int(elapsed)} 秒...")

        time.sleep(interval)
        elapsed = time.time() - start_time

    if verbose:
        print(f"[超时] 未检测到账号数据目录")
    return None


def wait_for_db_files(
    db_storage_path: Path,
    required_files: Optional[List[str]] = None,
    timeout: int = 30,
    interval: float = 2.0,
    verbose: bool = True
) -> bool:
    """
    等待关键数据库文件创建

    Args:
        db_storage_path: db_storage 目录路径
        required_files: 需要等待的文件列表，默认为 ['session/session.db', 'contact/contact.db']
        timeout: 超时时间（秒）
        interval: 检查间隔（秒）

    Returns:
        所有文件是否都已创建
    """
    if required_files is None:
        required_files = ['session/session.db', 'contact/contact.db']

    start_time = time.time()
    elapsed = 0

    if verbose:
        print(f"[等待] 等待数据库文件创建... (超时: {timeout}秒)")

    while elapsed < timeout:
        all_exists = True
        missing_files = []

        for file_path in required_files:
            full_path = db_storage_path / file_path
            if not full_path.exists():
                all_exists = False
                missing_files.append(file_path)

        if all_exists:
            if verbose:
                print(f"[OK] 所有关键数据库文件已就绪")
            return True

        if verbose and int(elapsed) % 10 == 0 and int(elapsed) > 0:
            print(f"[等待] 缺少文件: {', '.join(missing_files)}")

        time.sleep(interval)
        elapsed = time.time() - start_time

    if verbose:
        print(f"[警告] 部分数据库文件未创建: {missing_files}")
    return False


def wait_for_wechat_ready(
    account_id: Optional[str] = None,
    process_timeout: int = 60,
    data_dir_timeout: int = 60,
    db_files_timeout: int = 30,
    verbose: bool = True
) -> dict:
    """
    完整的微信初始化等待流程

    Args:
        account_id: 微信账号 ID（可选，如果不提供则只等待进程）
        process_timeout: 等待进程超时
        data_dir_timeout: 等待数据目录超时
        db_files_timeout: 等待数据库文件超时
        verbose: 是否显示进度

    Returns:
        {
            'success': bool,
            'pid': int or None,
            'db_storage_path': Path or None,
            'db_files_ready': bool
        }
    """
    result = {
        'success': False,
        'pid': None,
        'db_storage_path': None,
        'db_files_ready': False
    }

    # 阶段1: 等待进程
    if verbose:
        print("\n[阶段1] 等待微信进程...")

    pid = wait_for_wechat_process(timeout=process_timeout, verbose=verbose)
    if not pid:
        return result
    result['pid'] = pid

    # 如果没有提供账号ID，只等待进程
    if not account_id:
        result['success'] = True
        return result

    # 阶段2: 等待数据目录
    if verbose:
        print("\n[阶段2] 等待数据目录...")

    db_storage_path = wait_for_wechat_data_dir(
        account_id, timeout=data_dir_timeout, verbose=verbose
    )
    if not db_storage_path:
        return result
    result['db_storage_path'] = db_storage_path

    # 阶段3: 等待数据库文件
    if verbose:
        print("\n[阶段3] 等待数据库文件...")

    db_files_ready = wait_for_db_files(
        db_storage_path, timeout=db_files_timeout, verbose=verbose
    )
    result['db_files_ready'] = db_files_ready

    # 判断是否成功
    result['success'] = True  # 即使数据库文件未完全就绪，也认为初始化完成

    if verbose:
        print("\n[完成] 微信初始化等待完成")
        print(f"  - PID: {result['pid']}")
        print(f"  - 数据目录: {result['db_storage_path']}")
        print(f"  - 数据库文件: {'就绪' if result['db_files_ready'] else '部分就绪'}")

    return result


class WeChatWaiter:
    """微信初始化等待器类"""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose

    def wait_for_process(self, timeout: int = 60) -> Optional[int]:
        """等待微信进程启动"""
        return wait_for_wechat_process(timeout=timeout, verbose=self.verbose)

    def wait_for_data_dir(self, account_id: str, timeout: int = 60) -> Optional[Path]:
        """等待数据目录创建"""
        return wait_for_wechat_data_dir(account_id, timeout=timeout, verbose=self.verbose)

    def wait_for_db_files(self, db_storage_path: Path, timeout: int = 30) -> bool:
        """等待数据库文件创建"""
        return wait_for_db_files(db_storage_path, timeout=timeout, verbose=self.verbose)

    def wait_for_ready(self, account_id: Optional[str] = None) -> dict:
        """完整等待流程"""
        return wait_for_wechat_ready(account_id=account_id, verbose=self.verbose)