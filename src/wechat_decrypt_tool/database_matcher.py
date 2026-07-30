#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库匹配器模块

提供两个核心函数：
    - enumerate_session_dbs(): 枚举所有 session.db 候选
    - find_matching_database(): 找到密钥匹配的数据库

用于解决多数据目录场景下的密钥匹配问题。
"""

import hashlib
import hmac
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================================
# 常量定义
# ============================================================================

SQLITE_HEADER = b"SQLite format 3\x00"
PAGE_SIZE = 4096
KEY_SIZE = 32
SALT_SIZE = 16
IV_SIZE = 16
HMAC_SIZE = 64
RESERVE_SIZE = IV_SIZE + HMAC_SIZE


# ============================================================================
# 数据结构定义
# ============================================================================

@dataclass
class SessionDbCandidate:
    """session.db 候选项"""
    path: str                          # session.db 完整路径
    size: int                          # 文件大小
    mtime: float                       # 最后修改时间戳
    data_path: str                     # 所属账号目录（session.db 往上三级）
    account_name: str = ""             # 账号名称


@dataclass
class MatchResult:
    """匹配结果"""
    matched_path: Optional[str] = None      # 匹配的 session.db 路径
    matched_data_path: Optional[str] = None # 匹配的账号目录
    verified_at_retry: int = -1             # 第几次重试时匹配成功（-1表示未匹配）
    tried_paths: List[Dict[str, Any]] = field(default_factory=list)  # 所有尝试过的路径及结果


# ============================================================================
# 辅助函数
# ============================================================================

def _derive_mac_key(enc_key: bytes, salt: bytes) -> bytes:
    """Derive SQLCipher/WCDB page HMAC key."""
    mac_salt = bytes(b ^ 0x3A for b in salt)
    return hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=KEY_SIZE)


def _derive_sqlcipher_enc_key(key_material: bytes, salt: bytes) -> bytes:
    """Derive AES enc_key from SQLCipher passphrase/base key."""
    return hashlib.pbkdf2_hmac("sha512", key_material, salt, 256000, dklen=KEY_SIZE)


def _compute_page_hmac(mac_key: bytes, page: bytes, page_num: int) -> bytes:
    """计算页面 HMAC"""
    offset = SALT_SIZE if page_num == 1 else 0
    data_end = PAGE_SIZE - RESERVE_SIZE + IV_SIZE
    mac = hmac.new(mac_key, digestmod=hashlib.sha512)
    mac.update(page[offset:data_end])
    mac.update(page_num.to_bytes(4, "little"))
    return mac.digest()


def _is_valid_hex_key(key: str) -> bool:
    """验证密钥是否为有效的64位十六进制字符串"""
    if not key or len(key) != 64:
        return False
    try:
        bytes.fromhex(key)
        return True
    except ValueError:
        return False


def _verify_key_for_session_db(db_key: str, db_path: str) -> Tuple[bool, str]:
    """
    验证密钥是否匹配指定的 session.db
    
    Args:
        db_key: 64位十六进制密钥
        db_path: session.db 文件路径
        
    Returns:
        (是否匹配, 模式说明)
    """
    try:
        # 验证密钥格式
        if not _is_valid_hex_key(db_key):
            return False, f"密钥格式错误: 需要64位十六进制"
        
        key_bytes = bytes.fromhex(db_key)
        
        # 读取第一页
        with open(db_path, 'rb') as f:
            page1 = f.read(PAGE_SIZE)
        
        if len(page1) < PAGE_SIZE:
            return False, f"文件太小: {len(page1)} bytes"
        
        # 检查是否已是明文 SQLite
        if page1.startswith(SQLITE_HEADER):
            return True, "明文SQLite"
        
        # 尝试验证
        salt = page1[:SALT_SIZE]
        stored_hmac = page1[PAGE_SIZE - HMAC_SIZE: PAGE_SIZE]
        
        # 模式1: raw_enc_key（密钥直接作为加密密钥）
        mac_key_raw = _derive_mac_key(key_bytes, salt)
        expected_hmac_raw = _compute_page_hmac(mac_key_raw, page1, 1)
        if hmac.compare_digest(stored_hmac, expected_hmac_raw):
            return True, "raw_enc_key"
        
        # 模式2: sqlcipher_passphrase（密钥作为passphrase派生）
        derived_key = _derive_sqlcipher_enc_key(key_bytes, salt)
        mac_key_derived = _derive_mac_key(derived_key, salt)
        expected_hmac_derived = _compute_page_hmac(mac_key_derived, page1, 1)
        if hmac.compare_digest(stored_hmac, expected_hmac_derived):
            return True, "sqlcipher_passphrase"
        
        return False, "HMAC不匹配"
        
    except FileNotFoundError:
        return False, "文件不存在"
    except PermissionError:
        return False, "文件被锁定"
    except Exception as e:
        return False, f"异常: {e}"


# ============================================================================
# 核心函数
# ============================================================================

def enumerate_session_dbs(data_dirs: List[str]) -> List[SessionDbCandidate]:
    """
    枚举所有 session.db 候选
    
    Args:
        data_dirs: auto_detect_wechat_data_dirs() 返回的数据目录列表
        
    Returns:
        按修改时间降序排列的候选列表
        
    处理逻辑:
        - 遍历每个数据目录，递归搜索 session.db
        - 只保留 db_storage 或 session 路径下的文件（过滤同名无关文件）
        - 过滤掉小于 4096 字节的文件（不足一页，无法做 HMAC 验证）
        - 去重（不同基础路径可能扫描到同一文件）
        - 按修改时间降序排列（最近修改的优先验证）
    """
    candidates: List[SessionDbCandidate] = []
    seen_paths: set = set()
    
    for data_dir in data_dirs:
        if not os.path.exists(data_dir):
            continue
            
        try:
            # 递归搜索 session.db
            for root, dirs, files in os.walk(data_dir):
                # 过滤：只保留 db_storage 或 session 路径下的文件
                root_lower = root.lower()
                if "db_storage" not in root_lower and "session" not in root_lower:
                    continue
                    
                for file_name in files:
                    if file_name.lower() != "session.db":
                        continue
                        
                    file_path = os.path.join(root, file_name)
                    normalized_path = os.path.normpath(file_path)
                    
                    # 去重
                    if normalized_path in seen_paths:
                        continue
                    seen_paths.add(normalized_path)
                    
                    try:
                        # 获取文件信息
                        file_stat = os.stat(file_path)
                        file_size = file_stat.st_size
                        
                        # 过滤掉小于 4096 字节的文件
                        if file_size < 4096:
                            continue
                            
                        # 计算所属账号目录（session.db 往上三级）
                        # 例如: E:\xwechat_files\ToweR1989_b2c9\db_storage\session.db
                        # 往上三级: E:\xwechat_files\ToweR1989_b2c9
                        path_obj = Path(file_path)
                        path_parts = path_obj.parts
                        if len(path_parts) >= 4:
                            data_path = str(Path(*path_parts[:-3]))
                        else:
                            data_path = str(path_obj.parent.parent.parent)
                        
                        # 提取账号名称
                        account_name = Path(data_path).name if data_path else ""
                        
                        candidate = SessionDbCandidate(
                            path=normalized_path,
                            size=file_size,
                            mtime=file_stat.st_mtime,
                            data_path=data_path,
                            account_name=account_name
                        )
                        candidates.append(candidate)
                        
                    except (PermissionError, OSError):
                        # 跳过无法访问的文件
                        continue
                        
        except PermissionError:
            # 跳过无权限的目录
            continue
    
    # 按修改时间降序排列
    candidates.sort(key=lambda x: x.mtime, reverse=True)
    
    return candidates


def find_matching_database(
    db_key: str, 
    candidates: List[SessionDbCandidate],
    max_retries: int = 3,
    retry_interval: int = 10
) -> MatchResult:
    """
    找到密钥匹配的数据库
    
    Args:
        db_key: 64位十六进制密钥
        candidates: 候选列表（应按修改时间降序排列）
        max_retries: 最大重试次数
        retry_interval: 重试间隔（秒）
        
    Returns:
        匹配结果
        
    处理逻辑:
        - 每次重试：遍历所有候选，对每个 session.db 读取第一页做 HMAC 验证
        - 首次尝试只验证修改时间最新的几个候选（优化性能）
        - 重试时扩展到全部候选
        - 如果某次验证发现文件被锁定（PermissionError），跳过该文件继续下一个
        - 重试间隔等待（等微信完成初始化并写入 session.db）
    """
    result = MatchResult()
    
    # 空候选列表
    if not candidates:
        return result
    
    # 无效密钥格式
    if not _is_valid_hex_key(db_key):
        return result
    
    for retry_num in range(max_retries):
        # 首次尝试只验证前几个（修改时间最新的）
        # 重试时验证全部候选
        candidates_to_try = candidates if retry_num > 0 else candidates[:5]
        
        for candidate in candidates_to_try:
            matched, mode = _verify_key_for_session_db(db_key, candidate.path)
            
            tried_info = {
                "path": candidate.path,
                "size": candidate.size,
                "mtime": candidate.mtime,
                "matched": matched,
                "mode": mode,
                "retry": retry_num + 1
            }
            result.tried_paths.append(tried_info)
            
            if matched:
                result.matched_path = candidate.path
                result.matched_data_path = candidate.data_path
                result.verified_at_retry = retry_num + 1
                return result
        
        # 如果全部验证失败且还有重试机会，等待后继续
        if retry_num < max_retries - 1:
            time.sleep(retry_interval)
    
    return result


# ============================================================================
# 模块导出
# ============================================================================

__all__ = [
    'SessionDbCandidate',
    'MatchResult',
    'enumerate_session_dbs',
    'find_matching_database',
    '_verify_key_for_session_db',
]