#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TDD 测试文件：数据库匹配器

测试目标：验证《变更提案：密钥获取与数据库定位的稳定性修复.md》中的两个核心函数：
    - enumerate_session_dbs(): 枚举所有 session.db 候选
    - find_matching_database(): 找到密钥匹配的数据库

测试设计：
    - 测试组 A (A01-A10): enumerate_session_dbs 函数
    - 测试组 B (B01-B14): find_matching_database 函数
    - 测试组 C (C01-C05): 集成场景

TDD 流程：
    - 初始状态：所有测试应为红灯（函数不存在或功能未实现）
    - 实现后：所有测试应转为绿灯

运行方法：
    pytest tests/test_database_matcher.py -v

验收标准：
    - A01-C05 全部测试从红灯转为绿灯
"""

import hashlib
import hmac
import os
import struct
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, mock_open, patch

import pytest

# 添加 src 目录到 Python 路径
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# ============================================================================
# 数据结构定义（与实现代码保持一致）
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
    verified_at_retry: int = -1             # 第几次重试时匹配成功
    tried_paths: List[Dict[str, Any]] = field(default_factory=list)  # 所有尝试过的路径及结果


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
# 测试组 A：enumerate_session_dbs
# ============================================================================

class TestEnumerateSessionDbs:
    """
    测试 enumerate_session_dbs 函数
    
    输入: auto_detect_wechat_data_dirs() 返回的数据目录列表
    输出: 按修改时间降序排列的候选列表
    """
    
    def test_A01_multiple_dirs_with_session_db(self):
        """
        A01: 多数据目录各有 session.db
        
        红灯条件: 函数不存在
        覆盖边界: 正常多目录场景
        """
        # 导入函数（预期失败：函数不存在）
        from wechat_decrypt_tool.database_matcher import enumerate_session_dbs
        
        # 创建模拟的多目录结构
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建两个数据目录
            dir1 = Path(tmpdir) / "dir1" / "db_storage"
            dir2 = Path(tmpdir) / "dir2" / "db_storage"
            dir1.mkdir(parents=True)
            dir2.mkdir(parents=True)
            
            # 创建 session.db 文件
            session1 = dir1 / "session.db"
            session2 = dir2 / "session.db"
            
            # 写入大于 4096 字节的数据
            session1.write_bytes(b'\x00' * 8192)
            session2.write_bytes(b'\x00' * 8192)
            
            # 调用函数
            candidates = enumerate_session_dbs([str(dir1.parent), str(dir2.parent)])
            
            # 断言：应找到两个候选
            assert len(candidates) == 2, f"应找到2个候选，实际: {len(candidates)}"
            
            # 断言：每个候选应包含必要字段
            for c in candidates:
                assert c.path.endswith("session.db")
                assert c.size >= 4096
                assert c.mtime > 0
                assert c.data_path  # 非空
    
    def test_A02_empty_directory_list(self):
        """
        A02: 空目录列表
        
        红灯条件: 函数不存在
        覆盖边界: 无数据可搜
        """
        from wechat_decrypt_tool.database_matcher import enumerate_session_dbs
        
        # 空列表
        candidates = enumerate_session_dbs([])
        assert candidates == [], f"空列表应返回空结果，实际: {candidates}"
    
    def test_A03_directory_without_session_db(self):
        """
        A03: 目录下无 session.db
        
        红灯条件: 函数不存在
        覆盖边界: 目录存在但无目标文件
        """
        from wechat_decrypt_tool.database_matcher import enumerate_session_dbs
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建空目录
            empty_dir = Path(tmpdir) / "empty"
            empty_dir.mkdir()
            
            candidates = enumerate_session_dbs([str(empty_dir)])
            assert candidates == [], f"无 session.db 的目录应返回空结果，实际: {candidates}"
    
    def test_A04_session_db_too_small(self):
        """
        A04: session.db 小于 4096 字节
        
        红灯条件: 函数存在但无过滤逻辑
        覆盖边界: 损坏/空数据库
        """
        from wechat_decrypt_tool.database_matcher import enumerate_session_dbs
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建目录
            db_dir = Path(tmpdir) / "db_storage"
            db_dir.mkdir()
            
            # 创建小于 4096 字节的 session.db
            small_session = db_dir / "session.db"
            small_session.write_bytes(b'\x00' * 1024)  # 1KB
            
            candidates = enumerate_session_dbs([str(tmpdir)])
            
            # 断言：小文件应被过滤
            assert len(candidates) == 0, f"小于4096字节的文件应被过滤，实际找到: {len(candidates)}"
    
    def test_A05_duplicate_paths_from_different_base_dirs(self):
        """
        A05: 同一文件被多个基础路径覆盖
        
        红灯条件: 函数存在但无去重
        覆盖边界: 路径重叠
        """
        from wechat_decrypt_tool.database_matcher import enumerate_session_dbs
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建目录结构
            db_dir = Path(tmpdir) / "account" / "db_storage"
            db_dir.mkdir(parents=True)
            
            session_file = db_dir / "session.db"
            session_file.write_bytes(b'\x00' * 8192)
            
            # 用不同的基础路径调用（都包含同一个 session.db）
            candidates = enumerate_session_dbs([
                str(Path(tmpdir) / "account"),  # 账号目录
                str(tmpdir),                     # 更上层目录
            ])
            
            # 断言：应去重，只返回一个候选
            assert len(candidates) == 1, f"去重后应只有1个候选，实际: {len(candidates)}"
    
    def test_A06_directory_without_permission(self):
        """
        A06: 目录无访问权限
        
        红灯条件: 函数存在但无异常处理
        覆盖边界: 权限问题
        """
        from wechat_decrypt_tool.database_matcher import enumerate_session_dbs
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建无权限目录
            no_perm_dir = Path(tmpdir) / "no_permission"
            no_perm_dir.mkdir()
            
            # 尝试设置无权限（Windows 可能不支持，所以用 mock）
            with patch('os.walk') as mock_walk:
                # 模拟 os.walk 抛出 PermissionError
                mock_walk.side_effect = PermissionError("访问被拒绝")
                
                # 函数应优雅处理异常，返回空列表而不是抛出
                candidates = enumerate_session_dbs([str(no_perm_dir)])
                
                # 断言：应返回空列表（不崩溃）
                assert isinstance(candidates, list)
    
    def test_A07_sorted_by_mtime_descending(self):
        """
        A07: 结果按修改时间降序排列
        
        红灯条件: 函数存在但无排序
        覆盖边界: 优先验证最新目录
        """
        from wechat_decrypt_tool.database_matcher import enumerate_session_dbs
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建三个 session.db 文件，设置不同的修改时间
            paths = []
            for i in range(3):
                db_dir = Path(tmpdir) / f"dir{i}" / "db_storage"
                db_dir.mkdir(parents=True)
                session_file = db_dir / "session.db"
                session_file.write_bytes(b'\x00' * 8192)
                paths.append(session_file)
                
                # 设置不同的修改时间
                mtime = time.time() - (i * 3600)  # 每隔1小时
                os.utime(session_file, (mtime, mtime))
            
            candidates = enumerate_session_dbs([str(tmpdir)])
            
            # 断言：应按修改时间降序排列
            mtimes = [c.mtime for c in candidates]
            assert mtimes == sorted(mtimes, reverse=True), \
                f"应按修改时间降序排列，实际: {mtimes}"
    
    def test_A08_path_with_chinese_and_spaces(self):
        """
        A08: 路径含中文和空格
        
        红灯条件: 函数存在但编码处理错误
        覆盖边界: 中文环境路径
        """
        from wechat_decrypt_tool.database_matcher import enumerate_session_dbs
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建包含中文和空格的目录
            chinese_dir = Path(tmpdir) / "微信数据 目录" / "db_storage"
            chinese_dir.mkdir(parents=True)
            
            session_file = chinese_dir / "session.db"
            session_file.write_bytes(b'\x00' * 8192)
            
            candidates = enumerate_session_dbs([str(Path(tmpdir) / "微信数据 目录")])
            
            # 断言：应正确处理中文路径
            assert len(candidates) == 1, f"应找到1个候选，实际: {len(candidates)}"
            assert "微信数据 目录" in candidates[0].path or "微信数据" in candidates[0].path
    
    def test_A09_nested_wechat_files_structure(self):
        """
        A09: 嵌套 "WeChat Files" 子目录结构
        
        红灯条件: 函数存在但只搜一层
        覆盖边界: 旧版微信目录结构
        """
        from wechat_decrypt_tool.database_matcher import enumerate_session_dbs
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建旧版微信的深层目录结构
            # WeChat Files/account/db_storage/session.db
            deep_dir = Path(tmpdir) / "WeChat Files" / "account" / "db_storage"
            deep_dir.mkdir(parents=True)
            
            session_file = deep_dir / "session.db"
            session_file.write_bytes(b'\x00' * 8192)
            
            candidates = enumerate_session_dbs([str(tmpdir)])
            
            # 断言：应递归找到深层目录中的文件
            assert len(candidates) == 1, f"应找到深层目录中的session.db，实际: {len(candidates)}"
    
    def test_A10_multiple_session_db_layouts(self):
        """
        A10: 同时存在 db_storage/session/ 和 db_storage/ 下的 session.db
        
        红灯条件: 函数存在但路径过滤过严
        覆盖边界: 多种目录布局
        """
        from wechat_decrypt_tool.database_matcher import enumerate_session_dbs
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建两种目录布局
            # 布局1: account/db_storage/session.db
            layout1 = Path(tmpdir) / "account1" / "db_storage"
            layout1.mkdir(parents=True)
            (layout1 / "session.db").write_bytes(b'\x00' * 8192)
            
            # 布局2: account/session/session.db
            layout2 = Path(tmpdir) / "account2" / "session"
            layout2.mkdir(parents=True)
            (layout2 / "session.db").write_bytes(b'\x00' * 8192)
            
            candidates = enumerate_session_dbs([str(tmpdir)])
            
            # 断言：应找到两种布局的 session.db
            assert len(candidates) == 2, f"应找到两种布局共2个候选，实际: {len(candidates)}"


# ============================================================================
# 测试组 B：find_matching_database
# ============================================================================

class TestFindMatchingDatabase:
    """
    测试 find_matching_database 函数
    
    输入: 64位十六进制密钥 + 候选列表 + 重试参数
    输出: 匹配结果
    """
    
    @pytest.fixture
    def valid_db_key(self):
        """有效的64位十六进制密钥"""
        return "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
    
    @pytest.fixture
    def sample_candidates(self):
        """示例候选列表"""
        return [
            SessionDbCandidate(
                path="/path/to/session1.db",
                size=8192,
                mtime=time.time(),
                data_path="/path/to/account1"
            ),
            SessionDbCandidate(
                path="/path/to/session2.db",
                size=8192,
                mtime=time.time() - 3600,
                data_path="/path/to/account2"
            )
        ]
    
    def test_B01_key_matches_first_candidate(self, valid_db_key, sample_candidates):
        """
        B01: 密钥匹配第一个候选
        
        红灯条件: 函数不存在
        覆盖边界: 正常场景-最优路径
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database
        
        # Mock 文件读取和 HMAC 验证
        with patch('builtins.open', mock_open(read_data=b'\x00' * PAGE_SIZE)):
            with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db') as mock_verify:
                # 第一个候选匹配
                mock_verify.side_effect = [
                    (True, "raw_enc_key"),   # 第一个匹配
                ]
                
                result = find_matching_database(valid_db_key, sample_candidates[:1])
                
                # 断言：应匹配成功
                assert result.matched_path == sample_candidates[0].path
                assert result.matched_data_path == sample_candidates[0].data_path
                assert result.verified_at_retry == 1
    
    def test_B02_key_matches_second_candidate(self, valid_db_key, sample_candidates):
        """
        B02: 密钥匹配第二个候选（第一个不匹配）
        
        红灯条件: 函数不存在
        覆盖边界: 多目录需逐一验证
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database
        
        with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db') as mock_verify:
            # 第一个不匹配，第二个匹配
            mock_verify.side_effect = [
                (False, "HMAC不匹配"),
                (True, "raw_enc_key"),
            ]
            
            result = find_matching_database(valid_db_key, sample_candidates)
            
            # 断言：应匹配第二个
            assert result.matched_path == sample_candidates[1].path
            assert result.verified_at_retry == 1
    
    def test_B03_key_matches_no_candidate(self, valid_db_key, sample_candidates):
        """
        B03: 密钥不匹配任何候选
        
        红灯条件: 函数不存在
        覆盖边界: 密钥错误或过期
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database
        
        with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db') as mock_verify:
            # 全部不匹配
            mock_verify.return_value = (False, "HMAC不匹配")
            
            result = find_matching_database(valid_db_key, sample_candidates, max_retries=1, retry_interval=0)
            
            # 断言：应无匹配
            assert result.matched_path is None
            assert result.verified_at_retry == -1
    
    def test_B04_empty_candidate_list(self, valid_db_key):
        """
        B04: 空候选列表
        
        红灯条件: 函数不存在
        覆盖边界: 无数据库可验证
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database
        
        result = find_matching_database(valid_db_key, [])
        
        # 断言：应返回空结果
        assert result.matched_path is None
    
    def test_B05_candidate_file_deleted(self, valid_db_key, sample_candidates):
        """
        B05: 候选文件不存在（已被删除）
        
        红灯条件: 函数存在但无 FileNotFoundError 处理
        覆盖边界: 文件被删
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database
        
        with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db') as mock_verify:
            # 第一个文件不存在
            mock_verify.side_effect = [
                (False, "文件不存在"),
                (True, "raw_enc_key"),
            ]
            
            result = find_matching_database(valid_db_key, sample_candidates, max_retries=1)
            
            # 断言：应跳过不存在的文件，继续验证其他候选
            assert result.matched_path == sample_candidates[1].path
    
    def test_B06_plaintext_sqlite_database(self, sample_candidates):
        """
        B06: session.db 已是明文 SQLite
        
        红灯条件: 函数存在但无明文检测
        覆盖边界: 无加密的数据库
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database, _verify_key_for_session_db
        
        # 创建明文 SQLite 文件
        with tempfile.TemporaryDirectory() as tmpdir:
            session_path = Path(tmpdir) / "session.db"
            
            # 写入 SQLite 文件头
            session_path.write_bytes(SQLITE_HEADER + b'\x00' * (PAGE_SIZE - 16))
            
            candidate = SessionDbCandidate(
                path=str(session_path),
                size=PAGE_SIZE,
                mtime=time.time(),
                data_path=tmpdir
            )
            
            # 任意密钥（明文数据库应匹配任何密钥）
            any_key = "0" * 64
            
            result = find_matching_database(any_key, [candidate], max_retries=1)
            
            # 断言：明文数据库应返回匹配成功
            assert result.matched_path == str(session_path)
    
    def test_B07_retry_success_after_initial_failure(self, valid_db_key, sample_candidates):
        """
        B07: 首次验证全部失败，重试后成功
        
        红灯条件: 函数存在但无重试逻辑
        覆盖边界: 微信刚重启，session.db 未写完
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database
        
        call_count = [0]
        
        def mock_verify(*args):
            call_count[0] += 1
            # 第1、2次调用失败（首轮两个候选都失败），第3次调用成功（重试时第一个候选成功）
            if call_count[0] <= 2:
                return (False, "HMAC不匹配")
            else:
                return (True, "raw_enc_key")
        
        with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db', side_effect=mock_verify):
            result = find_matching_database(
                valid_db_key, 
                sample_candidates, 
                max_retries=3, 
                retry_interval=0
            )
            
            # 断言：应在第2次重试时成功
            # 第1轮：验证两个候选都失败（调用1、2）
            # 第2轮：验证第一个候选成功（调用3）
            assert result.matched_path == sample_candidates[0].path
            assert result.verified_at_retry == 2
    
    def test_B08_retry_exhausted(self, valid_db_key, sample_candidates):
        """
        B08: 重试全部耗尽仍失败
        
        红灯条件: 函数存在但无 max_retries 控制
        覆盖边界: 超时退出
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database
        
        with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db') as mock_verify:
            mock_verify.return_value = (False, "HMAC不匹配")
            
            result = find_matching_database(
                valid_db_key,
                sample_candidates,
                max_retries=2,
                retry_interval=0
            )
            
            # 断言：应返回失败结果
            assert result.matched_path is None
            assert result.verified_at_retry == -1
    
    def test_B09_file_locked_by_wechat(self, valid_db_key, sample_candidates):
        """
        B09: 文件被微信锁定（PermissionError）
        
        红灯条件: 函数存在但无异常处理
        覆盖边界: 文件锁
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database
        
        with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db') as mock_verify:
            # 第一个文件被锁定
            mock_verify.side_effect = [
                (False, "文件被锁定"),
                (True, "raw_enc_key"),
            ]
            
            result = find_matching_database(valid_db_key, sample_candidates, max_retries=1)
            
            # 断言：应跳过锁定的文件，继续验证其他候选
            assert result.matched_path == sample_candidates[1].path
    
    def test_B10_invalid_key_format(self, sample_candidates):
        """
        B10: 密钥不是 64 位十六进制
        
        红灯条件: 函数存在但无格式校验
        覆盖边界: 错误格式密钥
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database
        
        # 错误格式的密钥
        invalid_keys = [
            "abc",                    # 太短
            "x" * 64,                 # 含非十六进制字符
            "",                       # 空字符串
        ]
        
        for invalid_key in invalid_keys:
            result = find_matching_database(invalid_key, sample_candidates, max_retries=1)
            
            # 断言：无效密钥应返回失败结果
            assert result.matched_path is None, f"无效密钥 '{invalid_key}' 应返回 None"
    
    def test_B11_raw_key_mode_success(self, sample_candidates):
        """
        B11: raw_key 模式验证通过
        
        红灯条件: 函数存在但只试一种模式
        覆盖边界: 微信 4.x raw key
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database
        
        with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db') as mock_verify:
            # raw_enc_key 模式成功
            mock_verify.return_value = (True, "raw_enc_key")
            
            result = find_matching_database("0" * 64, sample_candidates[:1], max_retries=1)
            
            assert result.matched_path is not None
    
    def test_B12_passphrase_mode_success(self, sample_candidates):
        """
        B12: passphrase 模式验证通过
        
        红灯条件: 函数存在但只试一种模式
        覆盖边界: 微信 4.x passphrase
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database
        
        with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db') as mock_verify:
            # sqlcipher_passphrase 模式成功
            mock_verify.return_value = (True, "sqlcipher_passphrase")
            
            result = find_matching_database("0" * 64, sample_candidates[:1], max_retries=1)
            
            assert result.matched_path is not None
    
    def test_B13_correct_data_path_returned(self, valid_db_key):
        """
        B13: 匹配成功后返回正确的 data_path
        
        红灯条件: 函数存在但路径计算错误
        覆盖边界: data_path 推导
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database
        
        # 创建明确的目录结构
        expected_data_path = "/path/to/WeChat Files/Account123"
        candidate = SessionDbCandidate(
            path="/path/to/WeChat Files/Account123/db_storage/session.db",
            size=8192,
            mtime=time.time(),
            data_path=expected_data_path
        )
        
        with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db') as mock_verify:
            mock_verify.return_value = (True, "raw_enc_key")
            
            result = find_matching_database(valid_db_key, [candidate], max_retries=1)
            
            # 断言：返回的 data_path 应正确
            assert result.matched_data_path == expected_data_path
    
    def test_B14_performance_with_many_candidates(self, valid_db_key):
        """
        B14: 10 个以上候选的性能在可接受范围内（<5秒）
        
        红灯条件: 函数存在但无性能优化
        覆盖边界: 大量候选
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database
        
        # 创建15个候选
        candidates = [
            SessionDbCandidate(
                path=f"/path/to/session{i}.db",
                size=8192,
                mtime=time.time() - i * 100,
                data_path=f"/path/to/account{i}"
            )
            for i in range(15)
        ]
        
        with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db') as mock_verify:
            # 最后一个匹配
            mock_verify.return_value = (True, "raw_enc_key")
            
            start_time = time.time()
            result = find_matching_database(valid_db_key, candidates, max_retries=1)
            elapsed_time = time.time() - start_time
            
            # 断言：应在5秒内完成
            assert elapsed_time < 5.0, f"验证耗时 {elapsed_time:.2f}秒，超过5秒限制"


# ============================================================================
# 测试组 C：集成场景
# ============================================================================

class TestIntegrationScenarios:
    """
    集成场景测试（Mock 模拟真实环境）
    """
    
    @pytest.fixture
    def multi_drive_setup(self):
        """模拟 E 盘和 F 盘各有一个 session.db"""
        return {
            "E_drive": [
                SessionDbCandidate(
                    path="E:/WeChat Files/Account1/db_storage/session.db",
                    size=370000,
                    mtime=time.time() - 3600,
                    data_path="E:/WeChat Files/Account1"
                )
            ],
            "F_drive": [
                SessionDbCandidate(
                    path="F:/WeChat Files/Account2/db_storage/session.db",
                    size=350000,
                    mtime=time.time() - 7200,
                    data_path="F:/WeChat Files/Account2"
                )
            ]
        }
    
    def test_C01_key_matches_E_drive(self, multi_drive_setup):
        """
        C01: 模拟 E 盘和 F 盘各有一个 session.db，密钥匹配 E 盘
        
        红灯条件: 集成函数不存在
        覆盖边界: 本次测试发现的实际问题
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database
        
        # 合并两个盘的候选（E盘更新，排在前面）
        all_candidates = multi_drive_setup["E_drive"] + multi_drive_setup["F_drive"]
        
        with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db') as mock_verify:
            # E盘匹配，F盘不匹配
            mock_verify.side_effect = [
                (True, "raw_enc_key"),      # E盘匹配
            ]
            
            db_key = "a" * 64
            result = find_matching_database(db_key, all_candidates, max_retries=1)
            
            # 断言：应匹配 E 盘
            assert "E:" in result.matched_path
            assert "E:" in result.matched_data_path
    
    def test_C02_directory_switch_after_restart(self, multi_drive_setup):
        """
        C02: 模拟微信重启后目录从 F 盘切换到 E 盘
        
        红灯条件: 集成函数不存在
        覆盖边界: Hook 杀重启场景
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database
        
        # 重启后 E 盘更新（修改时间更近），F 盘较旧
        e_candidates = multi_drive_setup["E_drive"]
        f_candidates = multi_drive_setup["F_drive"]
        
        # 按修改时间排序（E盘更新，应排在前面）
        all_candidates = e_candidates + f_candidates
        
        with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db') as mock_verify:
            # E盘（新目录）匹配
            mock_verify.side_effect = [
                (True, "raw_enc_key"),
            ]
            
            db_key = "b" * 64
            result = find_matching_database(db_key, all_candidates, max_retries=1)
            
            # 断言：应匹配更新修改时间更近的 E 盘
            assert "E:" in result.matched_path
    
    def test_C03_retry_success_simulation(self):
        """
        C03: 模拟首次重试失败、第二次重试成功
        
        红灯条件: 集成函数无重试
        覆盖边界: 微信初始化延迟
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database
        
        candidate = SessionDbCandidate(
            path="/path/to/session.db",
            size=8192,
            mtime=time.time(),
            data_path="/path/to/account"
        )
        
        call_count = [0]
        
        def mock_verify(*args):
            call_count[0] += 1
            # 首次失败，第二次成功
            return (call_count[0] > 1, "raw_enc_key" if call_count[0] > 1 else "HMAC不匹配")
        
        with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db', side_effect=mock_verify):
            result = find_matching_database("c" * 64, [candidate], max_retries=3, retry_interval=0)
            
            # 断言：应在第2次重试成功
            assert result.matched_path is not None
            assert result.verified_at_retry == 2
    
    def test_C04_single_directory_scenario(self):
        """
        C04: 模拟只有一个数据目录（最常见的单盘安装）
        
        红灯条件: 集成函数不存在
        覆盖边界: 标准安装场景
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database, enumerate_session_dbs
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # 单目录结构
            db_dir = Path(tmpdir) / "account" / "db_storage"
            db_dir.mkdir(parents=True)
            session_file = db_dir / "session.db"
            session_file.write_bytes(b'\x00' * 8192)
            
            # 枚举候选
            candidates = enumerate_session_dbs([str(Path(tmpdir) / "account")])
            
            # 断言：应找到1个候选
            assert len(candidates) == 1
    
    def test_C05_network_path_scenario(self):
        r"""
        C05: 模拟数据目录在网络路径 (\\server\share)
        
        红灯条件: 集成函数无超时处理
        覆盖边界: 网络驱动器
        """
        from wechat_decrypt_tool.database_matcher import find_matching_database
        
        # 网络路径候选
        candidate = SessionDbCandidate(
            path="\\\\server\\share\\WeChat\\Account\\db_storage\\session.db",
            size=8192,
            mtime=time.time(),
            data_path="\\\\server\\share\\WeChat\\Account"
        )
        
        with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db') as mock_verify:
            mock_verify.return_value = (True, "raw_enc_key")
            
            result = find_matching_database("d" * 64, [candidate], max_retries=1)
            
            # 断言：网络路径应能正常处理
            assert result.matched_path is not None


# ============================================================================
# 运行测试
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])