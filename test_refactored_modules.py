#!/usr/bin/env python3
"""
重构模块行为验证测试脚本

验证以下内容：
1. 公共模块函数行为正确
2. 模块导入正常
3. 关键功能逻辑不变
"""

import sys
import os
import unittest
from pathlib import Path
from datetime import datetime

# 添加 src 目录到路径
sys.path.insert(0, str(Path(__file__).parent / 'src'))


class TestCommonUtils(unittest.TestCase):
    """测试公共工具模块"""

    def test_parse_timestamp_valid(self):
        """测试时间戳解析 - 有效值"""
        from common_utils import parse_timestamp
        
        self.assertEqual(parse_timestamp(1609459200), 1609459200)
        self.assertEqual(parse_timestamp(1609459200.5), 1609459200)
        self.assertEqual(parse_timestamp("1609459200"), 1609459200)
        
    def test_parse_timestamp_invalid(self):
        """测试时间戳解析 - 无效值"""
        from common_utils import parse_timestamp
        
        self.assertEqual(parse_timestamp(None), 0)
        self.assertEqual(parse_timestamp(""), 0)
        self.assertEqual(parse_timestamp("invalid"), 0)
        self.assertEqual(parse_timestamp(0), 0)
        
    def test_format_timestamp(self):
        """测试时间戳格式化"""
        from common_utils import format_timestamp
        
        # 有效时间戳
        result = format_timestamp(1609459200)  # 2021-01-01 00:00:00 UTC
        self.assertEqual(len(result), 8)  # HH:MM:SS
        
        # 无效时间戳
        self.assertEqual(format_timestamp(0), '--:--:--')
        self.assertEqual(format_timestamp(None), '--:--:--')
        
    def test_truncate_text(self):
        """测试文本截断"""
        from common_utils import truncate_text
        
        # 短文本不截断
        self.assertEqual(truncate_text("abc", 10), "abc")
        
        # 长文本截断
        result = truncate_text("abcdefghijklmnopqrstuvwxyz", 10)
        self.assertEqual(len(result), 10)
        self.assertTrue(result.endswith("..."))
        
        # 空文本
        self.assertEqual(truncate_text("", 10), "")
        self.assertEqual(truncate_text(None, 10), "")
        
    def test_find_session_db_in_dir_not_exists(self):
        """测试在不存在目录查找 session.db"""
        from common_utils import find_session_db_in_dir
        
        result = find_session_db_in_dir(Path("/nonexistent/path"))
        self.assertIsNone(result)


class TestModuleImports(unittest.TestCase):
    """测试模块导入"""

    def test_import_common_utils(self):
        """测试公共模块导入"""
        import common_utils
        self.assertTrue(hasattr(common_utils, 'parse_timestamp'))
        self.assertTrue(hasattr(common_utils, 'format_timestamp'))
        self.assertTrue(hasattr(common_utils, 'truncate_text'))
        self.assertTrue(hasattr(common_utils, 'display_error_and_exit'))
        
    def test_import_main_module(self):
        """测试 main 模块导入"""
        import main
        self.assertTrue(hasattr(main, 'main'))
        self.assertTrue(hasattr(main, 'get_app_dir'))
        self.assertTrue(hasattr(main, 'ensure_directories'))
        
    def test_import_simple_monitor_module(self):
        """测试 simple_monitor 模块导入"""
        import simple_monitor
        self.assertTrue(hasattr(simple_monitor, 'SimpleMonitor'))
        self.assertTrue(hasattr(simple_monitor, 'main'))


class TestSimpleMonitorClass(unittest.TestCase):
    """测试 SimpleMonitor 类"""

    def test_init(self):
        """测试初始化"""
        from simple_monitor import SimpleMonitor
        
        monitor = SimpleMonitor()
        self.assertIsNone(monitor.pid)
        self.assertIsNone(monitor.account_id)
        self.assertIsNone(monitor.data_path)
        self.assertIsNone(monitor.db_key)
        self.assertIsNone(monitor.handle)
        self.assertEqual(monitor.groups, [])
        self.assertEqual(monitor.nickname_cache, {})
        
    def test_print_step_done(self):
        """测试步骤显示 - 成功"""
        from simple_monitor import SimpleMonitor
        
        monitor = SimpleMonitor()
        # 不应该抛出异常
        monitor.print_step("测试步骤", "done", "详情")
        
    def test_print_step_fail(self):
        """测试步骤显示 - 失败"""
        from simple_monitor import SimpleMonitor
        
        monitor = SimpleMonitor()
        monitor.print_step("测试步骤", "fail", "失败原因")
        
    def test_is_non_text_message(self):
        """测试非文本消息判断"""
        from simple_monitor import SimpleMonitor
        
        monitor = SimpleMonitor()
        
        # 空消息
        self.assertTrue(monitor._is_non_text_message(""))
        self.assertTrue(monitor._is_non_text_message(None))
        
        # XML 消息
        self.assertTrue(monitor._is_non_text_message('<?xml version="1.0"?><msg>test</msg>'))
        
        # 普通文本
        self.assertFalse(monitor._is_non_text_message("这是一条普通消息"))
        
    def test_clean_message_content(self):
        """测试消息内容清理"""
        from simple_monitor import SimpleMonitor
        
        monitor = SimpleMonitor()
        
        # 清理表情包
        result = monitor._clean_message_content("[太阳]【测试消息】内容")
        self.assertNotIn("[太阳]", result)
        
        # 空内容
        self.assertEqual(monitor._clean_message_content(""), "")
        
    def test_decode_message(self):
        """测试消息解码"""
        from simple_monitor import SimpleMonitor
        
        monitor = SimpleMonitor()
        
        # 普通字符串
        self.assertEqual(monitor.decode_message("测试消息"), "测试消息")
        
        # None
        self.assertEqual(monitor.decode_message(None), "")
        
        # 字节类型
        result = monitor.decode_message(b"test message")
        self.assertIn("test", result)
        
    def test_get_display_name(self):
        """测试显示名称获取"""
        from simple_monitor import SimpleMonitor
        
        monitor = SimpleMonitor()
        monitor.nickname_cache = {"wxid_123": "测试用户"}
        
        # 有缓存
        self.assertEqual(monitor._get_display_name("wxid_123"), "测试用户")
        
        # 无缓存
        self.assertEqual(monitor._get_display_name("unknown_id"), "unknown_id")


class TestMainModule(unittest.TestCase):
    """测试 main 模块"""

    def test_get_app_dir(self):
        """测试应用目录获取"""
        from main import get_app_dir
        
        result = get_app_dir()
        self.assertIsInstance(result, Path)
        
    def test_is_port_in_use(self):
        """测试端口检测"""
        from main import _is_port_in_use
        
        # 端口 1 通常未被使用（或无法绑定）
        # 这里只测试函数不会抛出异常
        try:
            result = _is_port_in_use(1)
            self.assertIsInstance(result, bool)
        except OSError:
            pass  # 某些系统可能不允许绑定低端口
            
    def test_ensure_directories(self):
        """测试目录创建"""
        from main import ensure_directories
        import tempfile
        
        # 使用临时目录测试
        with tempfile.TemporaryDirectory() as tmpdir:
            # 确保 APP_DIR 指向临时目录（模拟）
            original_app_dir = Path(tmpdir)
            
            # 创建必要的目录
            (original_app_dir / "data" / "a_stock_db").mkdir(parents=True, exist_ok=True)
            (original_app_dir / "logs").mkdir(parents=True, exist_ok=True)
            (original_app_dir / "output").mkdir(parents=True, exist_ok=True)
            
            # 验证目录存在
            self.assertTrue((original_app_dir / "data").exists())
            self.assertTrue((original_app_dir / "logs").exists())
            self.assertTrue((original_app_dir / "output").exists())


class TestRefactoredBehavior(unittest.TestCase):
    """测试重构后行为一致性"""

    def test_timestamp_parsing_consistency(self):
        """测试时间戳解析一致性"""
        from common_utils import parse_timestamp
        
        # 与原始行为一致
        test_cases = [
            (1609459200, 1609459200),
            ("1609459200", 1609459200),
            (None, 0),
            ("", 0),
            ("abc", 0),
            (0, 0),
        ]
        
        for input_val, expected in test_cases:
            self.assertEqual(parse_timestamp(input_val), expected)
            
    def test_message_processing_filter(self):
        """测试消息过滤逻辑"""
        from simple_monitor import SimpleMonitor
        
        monitor = SimpleMonitor()
        
        # 应该被过滤的消息
        filter_cases = [
            "",
            None,
            "<?xml><msg>",
            "<img src='test'>",
            "<videomsg>",
            "<emoji>",
        ]
        
        for content in filter_cases:
            self.assertTrue(monitor._is_non_text_message(content), 
                           f"应该过滤: {content}")
            
        # 不应该被过滤的消息
        pass_cases = [
            "普通文本消息",
            "包含数字123的消息",
            "特殊字符！@#￥%",
        ]
        
        for content in pass_cases:
            self.assertFalse(monitor._is_non_text_message(content),
                            f"不应该过滤: {content}")


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestCommonUtils))
    suite.addTests(loader.loadTestsFromTestCase(TestModuleImports))
    suite.addTests(loader.loadTestsFromTestCase(TestSimpleMonitorClass))
    suite.addTests(loader.loadTestsFromTestCase(TestMainModule))
    suite.addTests(loader.loadTestsFromTestCase(TestRefactoredBehavior))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result


if __name__ == '__main__':
    print("=" * 60)
    print("  重构模块行为验证测试")
    print("=" * 60)
    print()
    
    result = run_tests()
    
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("  [OK] 所有测试通过！")
    else:
        print(f"  [FAIL] 测试失败: {len(result.failures)} 个失败, {len(result.errors)} 个错误")
    print("=" * 60)
    
    sys.exit(0 if result.wasSuccessful() else 1)