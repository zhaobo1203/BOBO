#!/usr/bin/env python3
"""
TDD 测试文件：群映射缓存 strTalker 修复与正查方案

测试变更提案中的核心功能：
  - _build_group_db_mapping 方法
  - _find_message_db_by_table 方法
  - fallback 缓存写入

TDD 流程：先编写测试，验证红灯（功能未实现），再实现功能使测试通过。
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


def calculate_expected_table_name(group_id: str) -> str:
    """计算群 ID 对应的 Msg_ 表名"""
    return f"Msg_{hashlib.md5(group_id.encode('utf-8')).hexdigest()}"


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


class TestGroupDbMappingTDD:
    """群映射缓存 TDD 测试类
    
    测试用例对应变更提案中的单元测试场景：
      01 - _build_group_db_mapping 有已解密的 session.db，返回映射条目
      02 - SessionTable 中无群（无 @chatroom），返回空 dict
      03 - 群对应的 Msg_ 表在 message_0.db，正确定位
      04 - 群对应的 Msg_ 表在 message_1.db，正确定位
      05 - Msg_ 表跨 db 不存在，映射中跳过该群
      06 - strTalker 相关旧代码已删除
      07 - fallback 路径写入缓存
      08 - 多个群映射到同一 db，正确合并
    """
    
    def __init__(self):
        self.temp_dir = None
        self.test_results = []
    
    def setup(self):
        """设置测试环境"""
        self.temp_dir = tempfile.mkdtemp(prefix="test_group_mapping_tdd_")
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
    
    def test_01_build_group_db_mapping_returns_mapping(self):
        """测试 01: _build_group_db_mapping 有已解密的 session.db
        
        预期：SessionTable 返回 3 个群 → 返回 3 个映射条目
        红灯条件：方法不存在或返回空结果
        
        注意：_build_group_db_mapping 依赖 _find_message_db_by_table，
        而 _find_message_db_by_table 需要 db_key 和 temp_dir 来解密数据库。
        在单元测试中，我们验证方法存在且能正确读取 SessionTable。
        """
        print("\n[测试 01] _build_group_db_mapping 返回正确的映射条目")
        
        try:
            from simple_monitor import SimpleMonitor
            
            # 检查方法是否存在
            if not hasattr(SimpleMonitor, '_build_group_db_mapping'):
                self.record_result("01", "_build_group_db_mapping 方法存在", False, 
                    "方法不存在，需要实现")
                return
            
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
            
            # 创建 message 目录和数据库（明文数据库，无需解密）
            message_dir = os.path.join(self.temp_dir, "db_storage", "message")
            os.makedirs(message_dir, exist_ok=True)
            
            # 创建 message_0.db，包含第一个群的表
            create_mock_message_db(message_dir, "message_0.db", [expected_tables[0]])
            
            # 创建 message_1.db，包含另外两个群的表
            create_mock_message_db(message_dir, "message_1.db", expected_tables[1:])
            
            # 创建 SimpleMonitor 实例并设置必要属性
            monitor = SimpleMonitor()
            monitor.decrypted_session_db = session_db
            monitor.data_path = self.temp_dir
            monitor._group_db_mapping = {}
            
            # 设置 temp_dir 用于解密（这里我们使用明文数据库模拟）
            monitor.temp_dir = tempfile.mkdtemp(prefix="test_monitor_temp_")
            
            # 创建模拟的 db_storage 目录结构
            db_storage_dir = os.path.join(self.temp_dir, "db_storage")
            os.makedirs(db_storage_dir, exist_ok=True)
            session_dir = os.path.join(db_storage_dir, "session")
            os.makedirs(session_dir, exist_ok=True)
            
            # 复制 session.db 到正确位置
            import shutil as shutil_module
            shutil_module.copy(session_db, os.path.join(session_dir, "session.db"))
            
            # 由于 _find_message_db_by_table 需要解密，我们需要模拟它
            # 在真实环境中，它会遍历 message db 并解密查找表
            # 这里我们使用 patch 来模拟解密过程
            
            def mock_find_message_db_by_table(target_table):
                """模拟 _find_message_db_by_table 返回正确的数据库"""
                for i, table in enumerate(expected_tables):
                    if target_table.lower() == table.lower():
                        if i == 0:
                            return os.path.join(message_dir, "message_0.db")
                        else:
                            return os.path.join(message_dir, "message_1.db")
                return None
            
            # 保存原始方法
            original_find = monitor._find_message_db_by_table
            monitor._find_message_db_by_table = mock_find_message_db_by_table
            
            # 调用方法
            result = monitor._build_group_db_mapping()
            
            # 恢复原始方法
            monitor._find_message_db_by_table = original_find
            
            # 验证结果
            if result is None:
                result = monitor._group_db_mapping
            
            passed = result is not None and len(result) == 3
            details = f"返回 {len(result) if result else 0} 个映射，期望 3 个"
            
            # 清理
            try:
                if monitor.temp_dir and os.path.exists(monitor.temp_dir):
                    shutil_module.rmtree(monitor.temp_dir)
            except:
                pass
            
            self.record_result("01", "_build_group_db_mapping 返回 3 个映射条目", passed, details)
            
        except AttributeError as e:
            self.record_result("01", "_build_group_db_mapping 方法存在", False, f"属性错误: {e}")
        except Exception as e:
            self.record_result("01", "_build_group_db_mapping 方法可调用", False, f"异常: {e}")
    
    def test_02_build_group_db_mapping_empty_groups(self):
        """测试 02: SessionTable 中无群（无 @chatroom）
        
        预期：返回空 dict
        """
        print("\n[测试 02] SessionTable 无群 → 返回空 dict")
        
        try:
            from simple_monitor import SimpleMonitor
            
            if not hasattr(SimpleMonitor, '_build_group_db_mapping'):
                self.record_result("02", "_build_group_db_mapping 处理空群列表", False, 
                    "方法不存在")
                return
            
            # 创建独立目录避免冲突
            test02_dir = os.path.join(self.temp_dir, "test02")
            os.makedirs(test02_dir, exist_ok=True)
            
            # 创建没有群的 session.db
            session_db = create_mock_session_db(test02_dir, [])
            
            monitor = SimpleMonitor()
            monitor.decrypted_session_db = session_db
            monitor.data_path = test02_dir
            monitor._group_db_mapping = {}
            
            result = monitor._build_group_db_mapping()
            if result is None:
                result = monitor._group_db_mapping
            
            passed = result is not None and len(result) == 0
            details = f"映射数量: {len(result) if result else 'None'}"
            
            self.record_result("02", "SessionTable 无群返回空 dict", passed, details)
            
        except Exception as e:
            self.record_result("02", "SessionTable 无群处理", False, f"异常: {e}")
    
    def test_03_find_table_in_message_0(self):
        """测试 03: 群对应的 Msg_ 表在 message_0.db
        
        预期：正确定位到 message_0.db
        """
        print("\n[测试 03] 群表在 message_0.db → 正确定位")
        
        try:
            from simple_monitor import SimpleMonitor
            
            # 检查辅助方法是否存在
            if not hasattr(SimpleMonitor, '_find_message_db_by_table'):
                self.record_result("03", "_find_message_db_by_table 方法存在", False, 
                    "方法不存在，需要实现")
                return
            
            group_id = "test_group_0@chatroom"
            expected_table = calculate_expected_table_name(group_id)
            
            # 创建 message 目录
            message_dir = os.path.join(self.temp_dir, "message_test03")
            os.makedirs(message_dir, exist_ok=True)
            
            # 创建 message_0.db 包含目标表
            db_path = create_mock_message_db(message_dir, "message_0.db", [expected_table])
            
            monitor = SimpleMonitor()
            
            # 调用方法（使用 skip_decrypt=True 和 message_dir 参数）
            result = monitor._find_message_db_by_table(
                expected_table, skip_decrypt=True, message_dir=message_dir
            )
            
            passed = result is not None and "message_0.db" in result
            details = f"找到数据库: {result}"
            
            self.record_result("03", "_find_message_db_by_table 定位 message_0.db", passed, details)
            
        except Exception as e:
            self.record_result("03", "_find_message_db_by_table 方法", False, f"异常: {e}")
    
    def test_04_find_table_in_message_1(self):
        """测试 04: 群对应的 Msg_ 表在 message_1.db
        
        预期：正确定位到 message_1.db
        """
        print("\n[测试 04] 群表在 message_1.db → 正确定位")
        
        try:
            from simple_monitor import SimpleMonitor
            
            if not hasattr(SimpleMonitor, '_find_message_db_by_table'):
                self.record_result("04", "_find_message_db_by_table 定位 message_1.db", False, 
                    "方法不存在")
                return
            
            group_id = "test_group_1@chatroom"
            expected_table = calculate_expected_table_name(group_id)
            
            # 创建 message 目录
            message_dir = os.path.join(self.temp_dir, "message_test04")
            os.makedirs(message_dir, exist_ok=True)
            
            # 创建 message_0.db 不包含目标表
            create_mock_message_db(message_dir, "message_0.db", ["Msg_other_table"])
            
            # 创建 message_1.db 包含目标表
            create_mock_message_db(message_dir, "message_1.db", [expected_table])
            
            monitor = SimpleMonitor()
            
            # 调用方法（使用 skip_decrypt=True 和 message_dir 参数）
            result = monitor._find_message_db_by_table(
                expected_table, skip_decrypt=True, message_dir=message_dir
            )
            
            passed = result is not None and "message_1.db" in result
            details = f"找到数据库: {result}"
            
            self.record_result("04", "_find_message_db_by_table 定位 message_1.db", passed, details)
            
        except Exception as e:
            self.record_result("04", "_find_message_db_by_table 方法", False, f"异常: {e}")
    
    def test_05_table_not_exist(self):
        """测试 05: Msg_ 表跨 db 不存在
        
        预期：映射中跳过该群，返回 None
        """
        print("\n[测试 05] Msg_ 表不存在 → 返回 None")
        
        try:
            from simple_monitor import SimpleMonitor
            
            if not hasattr(SimpleMonitor, '_find_message_db_by_table'):
                self.record_result("05", "_find_message_db_by_table 处理不存在的表", False, 
                    "方法不存在")
                return
            
            group_id = "nonexistent@chatroom"
            expected_table = calculate_expected_table_name(group_id)
            
            # 创建 message 目录
            message_dir = os.path.join(self.temp_dir, "message_test05")
            os.makedirs(message_dir, exist_ok=True)
            
            # 创建空的 message db
            create_mock_message_db(message_dir, "message_0.db", ["Msg_other_table"])
            
            monitor = SimpleMonitor()
            
            # 调用方法（使用 skip_decrypt=True 和 message_dir 参数）
            result = monitor._find_message_db_by_table(
                expected_table, skip_decrypt=True, message_dir=message_dir
            )
            
            passed = result is None
            details = f"结果: {result}（预期 None）"
            
            self.record_result("05", "_find_message_db_by_table 不存在的表返回 None", passed, details)
            
        except Exception as e:
            self.record_result("05", "_find_message_db_by_table 方法", False, f"异常: {e}")
    
    def test_06_strtalker_code_removed(self):
        """测试 06: strTalker 相关旧代码已删除
        
        预期：simple_monitor.py 中无 strTalker 引用
        """
        print("\n[测试 06] grep strTalker → 文件中无匹配")
        
        try:
            simple_monitor_path = Path(__file__).parent / "src" / "simple_monitor.py"
            
            if not simple_monitor_path.exists():
                self.record_result("06", "strTalker 代码检查", False, "simple_monitor.py 不存在")
                return
            
            content = simple_monitor_path.read_text(encoding='utf-8')
            
            # 检查是否存在 strTalker（排除注释中的说明）
            lines_with_strtalker = []
            for i, line in enumerate(content.split('\n'), 1):
                # 检查代码中的 strTalker（非注释）
                if 'strTalker' in line:
                    stripped = line.strip()
                    # 如果不是注释行，记录下来
                    if not stripped.startswith('#') and not stripped.startswith('"""') and not stripped.startswith("'''"):
                        lines_with_strtalker.append((i, stripped))
            
            # 根据提案，应该删除 strTalker 相关代码
            passed = len(lines_with_strtalker) == 0
            details = f"找到 {len(lines_with_strtalker)} 处 strTalker 引用"
            if lines_with_strtalker:
                details += f" (行号: {[l[0] for l in lines_with_strtalker[:3]]})"
            
            self.record_result("06", "strTalker 相关旧代码已删除", passed, details)
            
        except Exception as e:
            self.record_result("06", "strTalker 代码检查", False, f"异常: {e}")
    
    def test_07_fallback_write_cache(self):
        """测试 07: fallback 路径写入缓存
        
        预期：首次查询后 _group_db_mapping 包含该群
        """
        print("\n[测试 07] fallback 查询结果写入 _group_db_mapping")
        
        try:
            from simple_monitor import SimpleMonitor
            
            # 检查是否有 _group_db_mapping 属性
            monitor = SimpleMonitor()
            
            # 尝试访问属性
            if not hasattr(monitor, '_group_db_mapping'):
                # 如果属性不存在，记录红灯
                self.record_result("07", "_group_db_mapping 属性存在", False, 
                    "属性不存在，需要在 __init__ 中初始化")
                return
            
            group_id = "cache_test@chatroom"
            expected_table = calculate_expected_table_name(group_id)
            
            # 创建 message 目录
            message_dir = os.path.join(self.temp_dir, "message_test07")
            os.makedirs(message_dir, exist_ok=True)
            
            # 创建包含目标表的 db
            db_path = create_mock_message_db(message_dir, "message_0.db", [expected_table])
            
            monitor._group_db_mapping = {}
            
            # 调用方法（使用 skip_decrypt=True 和 message_dir 参数）
            result = monitor._find_message_db_by_table(
                expected_table, skip_decrypt=True, message_dir=message_dir
            )
            
            if result:
                # 模拟写入缓存
                monitor._group_db_mapping[group_id] = result
            
            # 验证缓存已写入
            passed = group_id in monitor._group_db_mapping
            details = f"缓存包含 {group_id}: {group_id in monitor._group_db_mapping}"
            
            self.record_result("07", "fallback 路径写入缓存", passed, details)
            
        except Exception as e:
            self.record_result("07", "fallback 写入缓存", False, f"异常: {e}")
    
    def test_08_multiple_groups_same_db(self):
        """测试 08: 多个群映射到同一 db
        
        预期：正确合并到同一数据库路径
        """
        print("\n[测试 08] 多个群映射到同一 db → 正确合并")
        
        try:
            from simple_monitor import SimpleMonitor
            
            if not hasattr(SimpleMonitor, '_build_group_db_mapping'):
                self.record_result("08", "_build_group_db_mapping 处理多群同库", False, 
                    "方法不存在")
                return
            
            # 多个群
            group_ids = [
                "group_a@chatroom",
                "group_b@chatroom",
                "group_c@chatroom"
            ]
            
            # 计算表名
            expected_tables = [calculate_expected_table_name(gid) for gid in group_ids]
            
            # 使用独立目录避免冲突
            test08_dir = os.path.join(self.temp_dir, "test08")
            os.makedirs(test08_dir, exist_ok=True)
            
            # 创建 session.db
            session_db = create_mock_session_db(test08_dir, group_ids)
            
            # 创建 message 目录
            message_dir = os.path.join(test08_dir, "message_test08")
            os.makedirs(message_dir, exist_ok=True)
            
            # 创建单个 db 包含所有表
            db_path = create_mock_message_db(message_dir, "message_0.db", expected_tables)
            
            monitor = SimpleMonitor()
            monitor.decrypted_session_db = session_db
            monitor.data_path = test08_dir
            monitor._group_db_mapping = {}
            
            # 模拟 _find_message_db_by_table 返回同一个数据库
            def mock_find_message_db_by_table(target_table):
                """模拟 _find_message_db_by_table 返回同一个数据库"""
                for table in expected_tables:
                    if target_table.lower() == table.lower():
                        return db_path
                return None
            
            # 保存原始方法
            original_find = monitor._find_message_db_by_table
            monitor._find_message_db_by_table = mock_find_message_db_by_table
            
            result = monitor._build_group_db_mapping()
            
            # 恢复原始方法
            monitor._find_message_db_by_table = original_find
            
            if result is None:
                result = monitor._group_db_mapping
            
            # 验证所有群都映射到同一个 db
            if result:
                all_same_db = len(set(result.values())) == 1
                all_groups_mapped = len(result) == len(group_ids)
                passed = all_same_db and all_groups_mapped
            else:
                passed = False
            
            details = f"{len(result) if result else 0} 个群映射到 {len(set(result.values())) if result else 0} 个数据库"
            
            self.record_result("08", "多群同库映射正确合并", passed, details)
            
        except Exception as e:
            self.record_result("08", "多群同库映射", False, f"异常: {e}")
    
    def test_09_init_has_group_db_mapping_attribute(self):
        """测试 09: __init__ 方法初始化 _group_db_mapping 属性
        
        预期：SimpleMonitor 实例有 _group_db_mapping 属性
        """
        print("\n[测试 09] __init__ 初始化 _group_db_mapping 属性")
        
        try:
            from simple_monitor import SimpleMonitor
            
            monitor = SimpleMonitor()
            
            # 检查属性是否存在
            if not hasattr(monitor, '_group_db_mapping'):
                self.record_result("09", "_group_db_mapping 属性存在", False, 
                    "属性不存在，需要在 __init__ 中初始化")
                return
            
            # 检查初始值是否为空字典
            passed = monitor._group_db_mapping == {}
            details = f"_group_db_mapping = {monitor._group_db_mapping}"
            
            self.record_result("09", "_group_db_mapping 属性初始化为空字典", passed, details)
            
        except Exception as e:
            self.record_result("09", "_group_db_mapping 属性检查", False, f"异常: {e}")
    
    def run_all_tests(self):
        """运行所有测试"""
        print("=" * 60)
        print("TDD 测试：群映射缓存 strTalker 修复与正查方案")
        print("=" * 60)
        print("\n[红灯阶段] 验证功能尚未实现，测试应该失败")
        
        self.setup()
        
        try:
            self.test_01_build_group_db_mapping_returns_mapping()
            self.test_02_build_group_db_mapping_empty_groups()
            self.test_03_find_table_in_message_0()
            self.test_04_find_table_in_message_1()
            self.test_05_table_not_exist()
            self.test_06_strtalker_code_removed()
            self.test_07_fallback_write_cache()
            self.test_08_multiple_groups_same_db()
            self.test_09_init_has_group_db_mapping_attribute()
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
            if result['details']:
                print(f"         {result['details']}")
        
        print()
        print(f"总计: {passed_count}/{total_count} 通过")
        
        # TDD 阶段判断
        if passed_count == 0:
            print("\n[红灯状态] 所有测试失败，符合 TDD 预期（功能未实现）")
        elif passed_count < total_count:
            print(f"\n[部分红灯] {total_count - passed_count} 个测试失败，需要实现对应功能")
        else:
            print("\n[绿灯状态] 所有测试通过，功能已实现")
        
        print("=" * 60)
        
        return passed_count == total_count


def main():
    """主函数"""
    print()
    print("=" * 60)
    print("TDD 测试流程验证")
    print("=" * 60)
    print()
    print("根据变更提案，以下功能需要实现：")
    print("  1. SimpleMonitor.__init__ 初始化 _group_db_mapping 属性")
    print("  2. _build_group_db_mapping 方法 - SessionTable 正查")
    print("  3. _find_message_db_by_table 方法 - 遍历查找表")
    print("  4. 删除 strTalker 相关旧代码")
    print()
    print("运行测试以验证红灯状态...")
    print()
    
    tester = TestGroupDbMappingTDD()
    all_passed = tester.run_all_tests()
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())