"""TN-02: 当前登录账号检测模块

功能：
- 自动检测微信数据目录
- 检测当前登录的账号ID
- 处理多账号场景
- 通过进程句柄关联账号
"""

import os
import re
import psutil
from typing import List, Dict, Optional
from pathlib import Path


def auto_detect_wechat_data_dirs() -> List[str]:
    """自动检测微信数据目录
    
    Returns:
        list: 数据目录路径列表
    """
    data_dirs = []
    
    # 常见的数据目录位置
    possible_paths = [
        os.path.expandvars(r"%USERPROFILE%\Documents\WeChat Files"),
        os.path.expandvars(r"%USERPROFILE%\Documents\xwechat_files"),
        "D:\\xwechat_files",
        "E:\\xwechat_files",
        "F:\\xwechat_files",
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            data_dirs.append(path)
    
    return data_dirs


def extract_account_from_path(file_path: str) -> Optional[str]:
    """从文件路径提取账号ID
    
    Args:
        file_path: 文件路径
        
    Returns:
        str: 账号ID，失败返回 None
    """
    # 微信 4.x 格式: {wxid}_{随机4位}/db_storage/...
    patterns = [
        r'[/\\]([^/\\]+)_([a-f0-9]{4})[/\\]',  # wxid_xxx_a2f9 格式
        r'[/\\]((?:wxid_)?[^/\\]+)[/\\]db_storage',  # wxid_xxx 或自定义ID
    ]
    
    for pattern in patterns:
        match = re.search(pattern, file_path, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return None


def detect_current_logged_in_account() -> Optional[Dict]:
    """通过进程句柄检测当前登录账号
    
    Returns:
        dict: 包含 current_account, pid, method 的字典，失败返回 None
    """
    wechat_processes = []
    
    # 查找微信进程
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            name = proc.info['name'].lower() if proc.info['name'] else ''
            if name in ['weixin.exe', 'wechat.exe']:
                wechat_processes.append(proc)
        except:
            continue
    
    if not wechat_processes:
        return None
    
    # 遍历进程的打开文件，查找账号
    for proc in wechat_processes:
        try:
            for item in proc.open_files():
                path = item.path.lower()
                if 'xwechat_files' in path or 'wechat files' in path:
                    account_id = extract_account_from_path(path)
                    if account_id:
                        return {
                            'current_account': account_id,
                            'pid': proc.info['pid'],
                            'method': 'process_handle'
                        }
        except:
            continue
    
    return None


def list_all_accounts(data_dir: str = None) -> List[Dict]:
    """列出所有账号
    
    Args:
        data_dir: 数据目录路径（可选）
        
    Returns:
        list: 账号列表，每个元素包含 account_id, data_path
    """
    if not data_dir:
        data_dirs = auto_detect_wechat_data_dirs()
        if not data_dirs:
            return []
        data_dir = data_dirs[0]
    
    accounts = []
    
    # 遍历目录查找账号
    try:
        for item in os.listdir(data_dir):
            item_path = os.path.join(data_dir, item)
            
            # 跳过非目录和特殊目录
            if not os.path.isdir(item_path):
                continue
            if item in ['All Users', 'Applet', 'WMPF', 'Public', 'SharedData']:
                continue
            
            # 检查是否是账号目录
            db_storage = os.path.join(item_path, 'db_storage')
            if os.path.exists(db_storage):
                # 提取账号ID
                # 格式可能是 wxid_xxx_a2f9 或自定义ID
                account_id = item.split('_')[0] if '_' in item else item
                
                # 如果是 wxid 格式，保留完整格式
                if item.startswith('wxid_'):
                    # 提取 wxid_xxx 部分
                    parts = item.split('_')
                    if len(parts) >= 2:
                        account_id = '_'.join(parts[:2])
                    else:
                        account_id = item
                else:
                    account_id = item
                
                accounts.append({
                    'account_id': account_id,
                    'data_path': item_path,
                    'dir_name': item
                })
    except Exception:
        pass
    
    return accounts


def get_account_info(account_id: str, data_dir: str = None) -> Optional[Dict]:
    """获取账号详细信息
    
    Args:
        account_id: 账号ID
        data_dir: 数据目录路径（可选）
        
    Returns:
        dict: 账号信息，包含 account_id, data_path, db_storage_path 等
    """
    if not data_dir:
        data_dirs = auto_detect_wechat_data_dirs()
        if not data_dirs:
            return None
        data_dir = data_dirs[0]
    
    # 查找匹配的账号目录
    for item in os.listdir(data_dir):
        item_path = os.path.join(data_dir, item)
        
        if not os.path.isdir(item_path):
            continue
        
        # 检查是否匹配账号ID
        if item.startswith(account_id) or item == account_id:
            db_storage = os.path.join(item_path, 'db_storage')
            if os.path.exists(db_storage):
                return {
                    'account_id': account_id,
                    'data_path': item_path,
                    'db_storage_path': db_storage,
                    'dir_name': item
                }
    
    return None