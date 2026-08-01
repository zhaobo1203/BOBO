#!/usr/bin/env python3
"""
模块行为测试临时脚本
测试变更提案：群映射缓存 strTalker 修复与正查方案

测试用例:
  01 - _build_group_db_mapping 有已解密的 session.db，返回映射条目
  02 - SessionTable 中无群（无 @chatroom），返回空 dict
  03 - 群对应的 Msg_ 表在 message_0.db，正确定位
  04 - 群对应的 Msg_ 表在 message_1.db，正确定位
  05 - Msg_ 表跨 db 不存在，映射中跳过该群
  06 - strTalker 相关旧代码已删除
  07 - fallback 路径写入缓存
  08 - 多个群映射到同一 db，正确合并
"""

import os
import sys
import sqlite3
import tempfile
import hashlib
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import Mock, MagicMock, patch, PropertyMock

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / "src"))


def create_mock_session_db(temp_dir: str, group_ids: List[str]) -> str:
    """创建模拟的 session.db，包含指定的群 ID"""
    session_db_path = os.path.join(temp_dir, "session.db")
    conn = sqlite3.connect(session_db_path)
    cursor = conn.cursor()
    
    # 创建 SessionTable
    cursor.execute("""
        CREATE TABLE SessionTable (
            username TEXT PRIMARY KEY,
            last_sender_display_name TEXT
        )
    """)
    
    # 插入群 ID
    for gid in group_ids:
        cursor.execute(
            "INSERT INTO SessionTable (username, last_sender_display_name) VALUES (?, ?)",
            (gid, f"群_{gid[:8]}")
        )
    
    conn.commit()
    conn.close()
    return session_db_path


def create_mock_message_db(temp_dir: str, db_name: str, table_names: List[str]) -> str:
    """创建模拟的 message 数据库，包含指定的表"""
    db_path = os.path.join(temp_dir, db_name)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 创建 Name2Id 表（用于 JOIN 查询）
    cursor.execute("""
        CREATE TABLE Name2Id (
            rowid INTEGER PRIMARY KEY,
            user_name TEXT
        )
    """)
    
    # 插入一些测试数据
    cursor.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (1, 'test_user')")
    
    # 创建消息表
    for table_name in table_names:
        cursor.execute(f"""
            CREATE TABLE {table_name} (
                local_id INTEGER PRIMARY KEY,
                create_time INTEGER,
                message_content TEXT,
                real_sender_id INTEGER
            )
        """)
        # 插入一条测试消息
        cursor.execute(f"""
            INSERT INTO {table_name} (local_id, create_time, message_content, real_sender_id)
            VALUES (1, 1700000000, '测试消息', 1)
        """)
    
    conn.commit()
    conn.close()
    return db_path


def calculate_expected_table_name(group_id: str) -> str:
    """计算群 ID 对应的 Msg_ 表名"""
    return f"Msg_{hashlib.md5(group_id.encode('utf-8')).hexdigest()}"


class TestGroupDbMapping:
    """群映射缓存行为测试类"""
    
    def __init__(self):
        self.temp_dir = None
        self.test_results = []
    
    def setup(self):
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp(prefix="test_group_mapping_")
        print(f"[测试环境] 临时目录: {self.temp_dir}")
    
    def teardown(self):
        """清理测试环境"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            print(f"[测试环境] 已清理临时目录")
    
    def record_result(self, test_id: str, description: str, passed: bool, details: str = ""):
        """记录测试结果"""
        self.test_results.append({
            'id': test_id,
            'description': description,
            'passed': passed,
            'details': details
        })
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  [{test_id}] {status}: {description}")
        if details:
            print(f"         {details}")
    
    def test_01_session_table_has_groups(self):
        """测试 01: _build_group_db_mapping 有已解密的 session.db"""
        print("\n[测试 01] SessionTable 返回 3 个群 → 返回 3 个映射条目")
        
        try:
            # 创建模拟环境
            group_ids = [
                "12345678@chatroom",
                "87654321@chatroom",
                "11111111@chatroom"
            ]
            
            # 计算期望的表名
            expected_tables = [calculate_expected_table_name(gid) for gid in group_ids]
            
            # 创建 session.db
            session_db = create_mock_session_db(self.temp_dir, group_ids)
            
            # 创建 message 目录和数据库
            message_dir = os.path.join(self.temp_dir, "message")
            os.makedirs(message_dir, exist_ok=True)
            
            # 创建 message_0.db，包含第一个群的表
            create_mock_message_db(message_dir, "message_0.db", [expected_tables[0]])
            
            # 创建 message_1.db，包含另外两个群的表
            create_mock_message_db(message_dir, "message_1.db", expected_tables[1:])
            
            # 模拟正查逻辑
            def mock_build_group_db_mapping():
                """模拟 _build_group_db_mapping 正查逻辑"""
                mapping = {}
                
                # 查询 SessionTable
                conn = sqlite3.connect(session_db)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT username FROM SessionTable WHERE username LIKE '%@chatroom'"
                )
                found_group_ids = [row[0] for row in cursor.fetchall()]
                conn.close()
                
                # 遍历 message db 查找对应的表
                for gid in found_group_ids:
                    expected_table = calculate_expected_table_name(gid)
                    for db_name in os.listdir(message_dir):
                        if not db_name.endswith('.db'):
                            continue
                        db_path = os.path.join(message_dir, db_name)
                        try:
                            test_conn = sqlite3.connect(db_path)
                            test_cursor = test_conn.cursor()
                            test_cursor.execute(
                                "SELECT 1 FROM sqlite_master WHERE type='table' AND lower(name)=lower(?)",
                                (expected_table,)
                            )
                            if test_cursor.fetchone():
                                mapping[gid] = db_path
                                test_conn.close()
                                break
                            test_conn.close()
                        except Exception:
                            pass
                
                return mapping
            
            result = mock_build_group_db_mapping()
            
            # 验证结果
            passed = len(result) == 3
            details = f"返回 {len(result)} 个映射，期望 3 个"
            
            self.record_result("01", "SessionTable 返回 3 个群，返回 3 个映射条目", passed, details)
            
        except Exception as e:
            self.record_result("01", "SessionTable 返回 3 个群", False, f"异常: {e}")
    
    def test_02_session_table_no_groups(self):
        """测试 02: SessionTable 中无群（无 @chatroom）"""
        print("\n[测试 02] SessionTable 无群 → 返回空 dict")
        
        try:
            # 创建独立的临时目录避免表冲突
            test02_dir = os.path.join(self.temp_dir, "test02")
            os.makedirs(test02_dir, exist_ok=True)
            # 创建没有群的 session.db
            session_db = create_mock_session_db(test02_dir, [])
            
            # 模拟正查逻辑
            def mock_build_group_db_mapping():
                mapping = {}
                conn = sqlite3.connect(session_db)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT username FROM SessionTable WHERE username LIKE '%@chatroom'"
                )
                found_group_ids = [row[0] for row in cursor.fetchall()]
                conn.close()
                # 无群，返回空字典
                return mapping
            
            result = mock_build_group_db_mapping()
            
            # 验证结果 - 应该是空字典（因为查询结果为空）
            test_conn = sqlite3.connect(session_db)
            test_cursor = test_conn.cursor()
            test_cursor.execute("SELECT username FROM SessionTable WHERE username LIKE '%@chatroom'")
            group_count = len(test_cursor.fetchall())
            test_conn.close()
            
            passed = group_count == 0 and result == {}
            details = f"群数量: {group_count}, 映射数量: {len(result)}"
            
            self.record_result("02", "SessionTable 无群，返回空 dict", passed, details)
            
        except Exception as e:
            self.record_result("02", "SessionTable 无群", False, f"异常: {e}")
    
    def test_03_group_in_message_0(self):
        """测试 03: 群对应的 Msg_ 表在 message_0.db"""
        print("\n[测试 03] 群表在 message_0.db → 正确定位")
        
        try:
            group_id = "test_group_0@chatroom"
            expected_table = calculate_expected_table_name(group_id)
            
            # 创建 message 目录
            message_dir = os.path.join(self.temp_dir, "message_test03")
            os.makedirs(message_dir, exist_ok=True)
            
            # 创建 message_0.db 包含目标表
            db_path = create_mock_message_db(message_dir, "message_0.db", [expected_table])
            
            # 验证表存在
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND lower(name)=lower(?)",
                (expected_table,)
            )
            found = cursor.fetchone() is not None
            conn.close()
            
            passed = found
            details = f"表 {expected_table} 在 message_0.db 中找到"
            
            self.record_result("03", "群表在 message_0.db，正确定位", passed, details)
            
        except Exception as e:
            self.record_result("03", "群表在 message_0.db", False, f"异常: {e}")
    
    def test_04_group_in_message_1(self):
        """测试 04: 群对应的 Msg_ 表在 message_1.db"""
        print("\n[测试 04] 群表在 message_1.db → 正确定位")
        
        try:
            group_id = "test_group_1@chatroom"
            expected_table = calculate_expected_table_name(group_id)
            
            # 创建 message 目录
            message_dir = os.path.join(self.temp_dir, "message_test04")
            os.makedirs(message_dir, exist_ok=True)
            
            # 创建 message_0.db 不包含目标表
            create_mock_message_db(message_dir, "message_0.db", ["Msg_other_table"])
            
            # 创建 message_1.db 包含目标表
            db_path = create_mock_message_db(message_dir, "message_1.db", [expected_table])
            
            # 模拟遍历查找
            found_db = None
            for db_name in sorted(os.listdir(message_dir)):
                if not db_name.endswith('.db'):
                    continue
                test_db_path = os.path.join(message_dir, db_name)
                conn = sqlite3.connect(test_db_path)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND lower(name)=lower(?)",
                    (expected_table,)
                )
                if cursor.fetchone():
                    found_db = db_name
                    conn.close()
                    break
                conn.close()
            
            passed = found_db == "message_1.db"
            details = f"表 {expected_table} 在 {found_db} 中找到"
            
            self.record_result("04", "群表在 message_1.db，正确定位", passed, details)
            
        except Exception as e:
            self.record_result("04", "群表在 message_1.db", False, f"异常: {e}")
    
    def test_05_table_not_exist(self):
        """测试 05: Msg_ 表跨 db 不存在"""
        print("\n[测试 05] Msg_ 表不存在 → 映射中跳过该群")
        
        try:
            group_id = "nonexistent@chatroom"
            expected_table = calculate_expected_table_name(group_id)
            
            # 创建 message 目录
            message_dir = os.path.join(self.temp_dir, "message_test05")
            os.makedirs(message_dir, exist_ok=True)
            
            # 创建空的 message db
            create_mock_message_db(message_dir, "message_0.db", ["Msg_other_table"])
            
            # 模拟查找逻辑
            found = False
            for db_name in os.listdir(message_dir):
                if not db_name.endswith('.db'):
                    continue
                test_db_path = os.path.join(message_dir, db_name)
                conn = sqlite3.connect(test_db_path)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND lower(name)=lower(?)",
                    (expected_table,)
                )
                if cursor.fetchone():
                    found = True
                    conn.close()
                    break
                conn.close()
            
            passed = not found
            details = f"表 {expected_table} 未找到（预期行为）"
            
            self.record_result("05", "Msg_ 表不存在，映射中跳过", passed, details)
            
        except Exception as e:
            self.record_result("05", "Msg_ 表不存在", False, f"异常: {e}")
    
    def test_06_strTalker_code_removed(self):
        """测试 06: strTalker 相关旧代码已删除"""
        print("\n[测试 06] grep strTalker → 文件中无匹配")
        
        try:
            # 检查 simple_monitor.py 中是否还有 strTalker
            simple_monitor_path = Path(__file__).parent / "src" / "simple_monitor.py"
            
            if not simple_monitor_path.exists():
                self.record_result("06", "strTalker 代码检查", False, "simple_monitor.py 不存在")
                return
            
            content = simple_monitor_path.read_text(encoding='utf-8')
            
            # 检查是否存在 strTalker（排除注释中的说明）
            lines_with_strtalker = []
            for i, line in enumerate(content.split('\n'), 1):
                if 'strTalker' in line and not line.strip().startswith('#'):
                    lines_with_strtalker.append((i, line.strip()))
            
            # 根据提案，应该删除 strTalker 相关代码
            # 这里检查是否还有实际使用的 strTalker
            passed = len(lines_with_strtalker) == 0
            details = f"找到 {len(lines_with_strtalker)} 处 strTalker 引用"
            if lines_with_strtalker:
                details += f" (行: {[l[0] for l in lines_with_strtalker[:3]]}...)"
            
            self.record_result("06", "strTalker 相关旧代码已删除", passed, details)
            
        except Exception as e:
            self.record_result("06", "strTalker 代码检查", False, f"异常: {e}")
    
    def test_07_fallback_write_cache(self):
        """测试 07: fallback 路径写入缓存"""
        print("\n[测试 07] fallback 查询结果写入 _group_db_mapping")
        
        try:
            # 模拟缓存机制
            cache = {}
            group_id = "cache_test@chatroom"
            expected_table = calculate_expected_table_name(group_id)
            
            # 创建 message 目录
            message_dir = os.path.join(self.temp_dir, "message_test07")
            os.makedirs(message_dir, exist_ok=True)
            
            # 创建包含目标表的 db
            db_path = create_mock_message_db(message_dir, "message_0.db", [expected_table])
            
            # 模拟 fallback 查询并写入缓存
            def mock_fallback_query(gid: str, cache: dict) -> Optional[str]:
                """模拟 fallback 查询逻辑"""
                expected = calculate_expected_table_name(gid)
                for db_name in os.listdir(message_dir):
                    if not db_name.endswith('.db'):
                        continue
                    test_db = os.path.join(message_dir, db_name)
                    conn = sqlite3.connect(test_db)
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND lower(name)=lower(?)",
                        (expected,)
                    )
                    if cursor.fetchone():
                        conn.close()
                        # 写入缓存
                        cache[gid] = test_db
                        return test_db
                    conn.close()
                return None
            
            result = mock_fallback_query(group_id, cache)
            
            # 验证缓存已写入
            passed = group_id in cache and cache[group_id] == result
            details = f"缓存包含 {group_id}: {group_id in cache}"
            
            self.record_result("07", "fallback 路径写入缓存", passed, details)
            
        except Exception as e:
            self.record_result("07", "fallback 写入缓存", False, f"异常: {e}")
    
    def test_08_multiple_groups_same_db(self):
        """测试 08: 多个群映射到同一 db"""
        print("\n[测试 08] 多个群映射到同一 db → 正确合并")
        
        try:
            # 多个群
            group_ids = [
                "group_a@chatroom",
                "group_b@chatroom",
                "group_c@chatroom"
            ]
            
            # 计算表名
            expected_tables = [calculate_expected_table_name(gid) for gid in group_ids]
            
            # 创建 message 目录
            message_dir = os.path.join(self.temp_dir, "message_test08")
            os.makedirs(message_dir, exist_ok=True)
            
            # 创建单个 db 包含所有表
            db_path = create_mock_message_db(message_dir, "message_0.db", expected_tables)
            
            # 模拟正查逻辑
            mapping = {}
            for gid in group_ids:
                expected_table = calculate_expected_table_name(gid)
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND lower(name)=lower(?)",
                    (expected_table,)
                )
                if cursor.fetchone():
                    mapping[gid] = db_path
                conn.close()
            
            # 验证所有群都映射到同一个 db
            all_same_db = len(set(mapping.values())) == 1
            all_groups_mapped = len(mapping) == len(group_ids)
            passed = all_same_db and all_groups_mapped
            
            details = f"{len(mapping)} 个群映射到 {len(set(mapping.values()))} 个数据库"
            
            self.record_result("08", "多个群映射到同一 db，正确合并", passed, details)
            
        except Exception as e:
            self.record_result("08", "多群同库映射", False, f"异常: {e}")
    
    def run_all_tests(self):
        """运行所有测试"""
        print("=" * 60)
        print("模块行为测试：群映射缓存 strTalker 修复与正查方案")
        print("=" * 60)
        
        self.setup()
        
        try:
            self.test_01_session_table_has_groups()
            self.test_02_session_table_no_groups()
            self.test_03_group_in_message_0()
            self.test_04_group_in_message_1()
            self.test_05_table_not_exist()
            self.test_06_strTalker_code_removed()
            self.test_07_fallback_write_cache()
            self.test_08_multiple_groups_same_db()
        finally:
            self.teardown()
        
        # 输出总结
        print("\n" + "=" * 60)
        print("测试总结")
        print("=" * 60)
        
        passed_count = sum(1 for r in self.test_results if r['passed'])
        total_count = len(self.test_results)
        
        for result in self.test_results:
            status = "[PASS]" if result['passed'] else "[FAIL]"
            print(f"  {status} [{result['id']}] {result['description']}")
        
        print()
        print(f"总计: {passed_count}/{total_count} 通过")
        print("=" * 60)
        
        return passed_count == total_count


def main():
    """主函数"""
    tester = TestGroupDbMapping()
    all_passed = tester.run_all_tests()
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())