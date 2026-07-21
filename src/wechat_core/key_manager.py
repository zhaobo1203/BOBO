"""TN-03: 数据库密钥获取模块

功能：
- V4 内存扫描获取密钥
- Hook 注入托底方案
- 密钥验证与存储
"""

import os
import json
import time
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

# 密钥存储文件路径
KEY_STORE_FILE = "key_store.json"


def check_wx_key_available() -> bool:
    """检查 wx-key 模块是否可用

    Returns:
        bool: 是否可用
    """
    try:
        import wx_key
        return True
    except ImportError:
        return False


def fetch_key_via_hook(wechat_exe_path: str, timeout_seconds: int = 60) -> Tuple[Optional[str], Optional[str]]:
    """通过 Hook 注入获取密钥

    Args:
        wechat_exe_path: 微信可执行文件路径
        timeout_seconds: 超时时间（秒）

    Returns:
        tuple: (密钥, 账号ID)，失败返回 (None, None)
    """
    if not check_wx_key_available():
        return None, None

    try:
        import wx_key
    except ImportError:
        return None, None

    # 启动微信
    process = subprocess.Popen(wechat_exe_path)
    time.sleep(3)

    # 查找微信进程
    import psutil
    pid = None
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            name = proc.info['name'].lower() if proc.info['name'] else ''
            if name in ['weixin.exe', 'wechat.exe']:
                pid = proc.info['pid']
                break
        except:
            continue

    if not pid:
        return None, None

    # 初始化 Hook
    if not wx_key.initialize_hook(pid):
        return None, None

    # 轮询获取密钥
    start_time = time.time()
    found_key = None
    found_account = None

    try:
        while time.time() - start_time < timeout_seconds:
            key_data = wx_key.poll_key_data()
            if key_data and 'key' in key_data:
                found_key = key_data['key']
                found_account = key_data.get('account', None)
                break
            time.sleep(0.5)
    finally:
        wx_key.cleanup_hook()

    return found_key, found_account


def get_key_store_path() -> str:
    """获取密钥存储文件路径

    Returns:
        str: 密钥存储文件路径
    """
    import sys

    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
    else:
        exe_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if os.path.basename(exe_dir) == 'src':
            exe_dir = os.path.dirname(exe_dir)

    return os.path.join(exe_dir, KEY_STORE_FILE)


def load_key_store() -> Dict:
    """加载密钥存储

    Returns:
        dict: 密钥存储内容
    """
    store_path = get_key_store_path()

    if not os.path.exists(store_path):
        return {'accounts': {}, 'aliases': {}}

    try:
        with open(store_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'accounts': {}, 'aliases': {}}


def save_key_to_store(account_id: str, db_key: str, nickname: str = None, data_path: str = None) -> bool:
    """保存密钥到存储

    Args:
        account_id: 账号ID
        db_key: 数据库密钥
        nickname: 昵称（可选）
        data_path: 数据路径（可选）

    Returns:
        bool: 是否保存成功
    """
    store_path = get_key_store_path()

    # 加载现有存储
    store = load_key_store()

    if 'accounts' not in store:
        store['accounts'] = {}

    # 更新账号密钥
    store['accounts'][account_id] = {
        'db_key': db_key,
        'nickname': nickname or account_id,
        'data_path': data_path,
        'last_updated': datetime.now().isoformat()
    }

    # 保存
    try:
        with open(store_path, 'w', encoding='utf-8') as f:
            json.dump(store, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def get_account_key(account_id: str) -> Optional[str]:
    """获取账号的密钥

    Args:
        account_id: 账号ID

    Returns:
        str: 密钥，失败返回 None
    """
    store = load_key_store()
    accounts = store.get('accounts', {})

    if account_id in accounts:
        return accounts[account_id].get('db_key')

    # 检查别名
    aliases = store.get('aliases', {})
    if account_id in aliases:
        real_id = aliases[account_id]
        if real_id in accounts:
            return accounts[real_id].get('db_key')

    return None


def get_all_account_keys() -> Dict:
    """获取所有账号的密钥

    Returns:
        dict: 账号ID到密钥的映射
    """
    store = load_key_store()
    accounts = store.get('accounts', {})

    return {
        account_id: info.get('db_key')
        for account_id, info in accounts.items()
        if info.get('db_key')
    }


def ensure_key_available(account_id: str, wechat_exe_path: str = None) -> Optional[str]:
    """确保账号密钥可用

    Args:
        account_id: 账号ID
        wechat_exe_path: 微信可执行文件路径（可选）

    Returns:
        str: 密钥，失败返回 None
    """
    # 首先检查是否已有密钥
    key = get_account_key(account_id)
    if key:
        return key

    # 如果没有，尝试通过 Hook 获取
    if wechat_exe_path and check_wx_key_available():
        key, _ = fetch_key_via_hook(wechat_exe_path)
        if key:
            save_key_to_store(account_id, key)
            return key

    return None
