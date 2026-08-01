#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集成测试：多目录切换场景下的数据库匹配

测试目标：验证重构后的数据库匹配逻辑能正确处理以下场景：
- 存在多个微信数据目录（如 E 盘旧数据 + F 盘新数据）
- Hook 杀重启微信后，微信切换到不同的数据目录
- 新逻辑能主动遍历所有目录，找到正确匹配的数据库

运行方法：
    pytest tests/test_database_matching_integration.py -v
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 添加 src 目录到 Python 路径
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from wechat_decrypt_tool.database_matcher import (
    SessionDbCandidate,
    MatchResult,
    enumerate_session_dbs,
    find_matching_database
)


class TestMultiDirectorySwitchIntegration:
    """多数据目录切换集成测试"""

    def test_scenario_multi_directories_after_restart(self):
        """
        场景：微信重启后目录从 F 盘切换到 E 盘
        
        模拟：
        1. 存在两个数据目录：F盘（旧）和 E盘（新，Hook重启后微信使用）
        2. 每个目录下各有一个 session.db
        3. 新密钥匹配 E盘的 session.db，不匹配 F盘
        4. 验证 find_matching_database 能正确找到 E盘
        """
        # 创建临时目录模拟两个数据盘
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            # 创建两个数据目录结构
            # F盘: F:/WeChat Files/old_user/db_storage/session.db
            f_dir = tmp_path / "F" / "WeChat Files" / "old_user" / "db_storage"
            f_dir.mkdir(parents=True)
            f_session = f_dir / "session.db"
            # 创建大于 4096 字节的文件
            f_session.write_bytes(b'\x00' * 8192)
            # 设置旧修改时间
            old_mtime = time.time() - 3600
            os.utime(f_session, (old_mtime, old_mtime))
            
            # E盘: E:/WeChat Files/new_user/db_storage/session.db
            e_dir = tmp_path / "E" / "WeChat Files" / "new_user" / "db_storage"
            e_dir.mkdir(parents=True)
            e_session = e_dir / "session.db"
            e_session.write_bytes(b'\x00' * 8192)
            # 设置新修改时间（重启后更新，时间更近）
            new_mtime = time.time()
            os.utime(e_session, (new_mtime, new_mtime))
            
            # 获取所有数据目录
            data_dirs = [
                str(tmp_path / "F" / "WeChat Files"),
                str(tmp_path / "E" / "WeChat Files"),
            ]
            
            # 枚举候选
            candidates = enumerate_session_dbs(data_dirs)
            
            # 应该找到两个候选
            assert len(candidates) == 2
            # 应该按修改时间降序排列，E盘（新）排在前面，且包含 new_user
            assert "new_user" in candidates[0].path
            
            # 模拟验证：E盘匹配，F盘不匹配
            with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db') as mock_verify:
                def side_effect(db_key, path):
                    if "new_user" in path:
                        return (True, "raw_enc_key")
                    else:
                        return (False, "HMAC不匹配")
                
                mock_verify.side_effect = side_effect
                
                # 任意有效64位密钥
                test_key = "a" * 64
                result = find_matching_database(test_key, candidates, max_retries=1)
                
                # 断言：匹配到 E盘
                assert result.matched_path is not None
                assert "new_user" in result.matched_path
                assert result.matched_data_path is not None
                # data_path 是往上三级，所以包含 E/WeChat Files，new_user 在 matched_path 已经验证
                assert "E" in result.matched_data_path or "e" in result.matched_data_path
                assert result.verified_at_retry == 1

    def test_scenario_key_changes_directory_switch(self):
        """
        场景：Hook触发后密钥变化，且微信切换目录
        
        模拟：
        1. 初始目录 F 盘，密钥 K1
        2. Hook重启后，密钥变为 K2，微信切换到 E 盘
        3. K2 只匹配 E 盘，不匹配 F 盘
        4. 验证：能正确找到 E 盘，而不是继续用 F 盘
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            # 创建两个目录
            dir_f = tmp_path / "f_wechat"
            dir_e = tmp_path / "e_wechat"
            (dir_f / "account_f" / "db_storage").mkdir(parents=True)
            (dir_e / "account_e" / "db_storage").mkdir(parents=True)
            
            f_session = dir_f / "account_f" / "db_storage" / "session.db"
            e_session = dir_e / "account_e" / "db_storage" / "session.db"
            f_session.write_bytes(b'\x00' * 8192)
            e_session.write_bytes(b'\x00' * 8192)
            
            data_dirs = [str(dir_f), str(dir_e)]
            candidates = enumerate_session_dbs(data_dirs)
            assert len(candidates) == 2
            
            # K2 只匹配 E盘
            with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db') as mock_verify:
                def side_effect(db_key, path):
                    if "account_e" in path:
                        return (True, "raw_enc_key")
                    return (False, "HMAC不匹配")
                
                mock_verify.side_effect = side_effect
                
                # 使用符合长度要求且全十六进制的密钥
                result = find_matching_database("a" * 64, candidates, max_retries=1)
                
                # 断言：正确匹配到 E盘，即使F盘是第一个检测到的目录
                assert result.matched_path is not None
                assert "account_e" in result.matched_path
                # data_dirs = [str(dir_f), str(dir_e)], candidates:
                # candidate 0: dir_f/account_f/... session.db -> data_path = dir_f
                # candidate 1: dir_e/account_e/... session.db -> data_path = dir_e
                assert result.matched_data_path == str(dir_e)

    def test_scenario_single_directory_fallback(self):
        """
        场景：只有一个数据目录（最常见的单盘安装）
        
        验证：新逻辑仍然正常工作，匹配唯一目录
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            # 单目录结构
            acc_dir = tmp_path / "WeChat Files" / "single_account" / "db_storage"
            acc_dir.mkdir(parents=True)
            session = acc_dir / "session.db"
            session.write_bytes(b'\x00' * 8192)
            
            data_dirs = [str(tmp_path / "WeChat Files")]
            candidates = enumerate_session_dbs(data_dirs)
            
            assert len(candidates) == 1
            # 当我们输入 data_dirs 为 WeChat Files，session.db 在 WeChat Files/single_account/db_storage
            # data_path 是 session.db 往上三级：db_storage -> single_account -> WeChat Files
            assert candidates[0].data_path == str(tmp_path / "WeChat Files")
            
            # 匹配成功
            with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db') as mock_verify:
                mock_verify.return_value = (True, "raw_enc_key")
                result = find_matching_database("a"*64, candidates)
                assert result.matched_path is not None
                assert result.verified_at_retry == 1

    def test_scenario_no_match_after_all_attempts(self):
        """
        场景：所有候选都不匹配密钥
        
        验证：返回正确的失败结果，不崩溃，记录所有尝试
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            # 创建三个候选
            for i in range(3):
                acc_dir = tmp_path / f"account_{i}" / "db_storage"
                acc_dir.mkdir(parents=True)
                session = acc_dir / "session.db"
                session.write_bytes(b'\x00' * 8192)
            
            data_dirs = [str(tmp_path)]
            candidates = enumerate_session_dbs(data_dirs)
            assert len(candidates) == 3
            
            # 所有都不匹配
            with patch('wechat_decrypt_tool.database_matcher._verify_key_for_session_db') as mock_verify:
                mock_verify.return_value = (False, "HMAC不匹配")
                result = find_matching_database("a"*64, candidates, max_retries=2, retry_interval=0)
                
                # 断言：匹配失败，但结果结构完整
                assert result.matched_path is None
                assert result.verified_at_retry == -1
                assert len(result.tried_paths) == 3 * 2  # 3个候选 x 2次重试
                # 所有尝试都记录
                for tried in result.tried_paths:
                    assert tried['matched'] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])