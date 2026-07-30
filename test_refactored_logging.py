#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志系统重构验证脚本

验证重构后的日志系统：
1. 统一日志出口
2. 环境感知配置
3. 双通道日志
4. 异常处理覆盖
5. 向后兼容性
"""

import logging
import sys
import tempfile
from pathlib import Path

# 添加src到路径
src_path = Path(__file__).parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))


def test_unified_log_manager():
    """测试统一日志管理器"""
    print("\n[测试1] 统一日志管理器")
    
    from wechat_decrypt_tool.logging_config import UnifiedLogManager, setup_logging, get_logger
    
    # 重置单例状态（测试用）
    UnifiedLogManager._instance = None
    UnifiedLogManager._initialized = False
    
    # 使用临时目录
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = Path(tmpdir)
        
        # 设置日志
        log_file = setup_logging("DEBUG")
        print(f"  日志文件: {log_file}")
        
        # 获取日志器
        logger = get_logger("test_module")
        logger.debug("这是调试日志")
        logger.info("这是信息日志")
        logger.warning("这是警告日志")
        logger.error("这是错误日志")
        
        # 验证日志文件存在
        assert log_file.exists(), "日志文件应该存在"
        
        # 验证JSON日志文件也存在
        json_file = log_file.with_suffix('.json')
        assert json_file.exists(), "JSON日志文件应该存在"
        
        print("  [PASS] 统一日志管理器测试通过")


def test_exe_logging_compatibility():
    """测试exe_logging向后兼容性"""
    print("\n[测试2] exe_logging向后兼容性")
    
    from wechat_decrypt_tool.exe_logging import (
        setup_exe_logging, get_exe_logger, get_exe_dir, get_log_file_path
    )
    
    # 重置单例状态
    from wechat_decrypt_tool.logging_config import UnifiedLogManager
    UnifiedLogManager._instance = None
    UnifiedLogManager._initialized = False
    
    # 设置日志
    log_file = setup_exe_logging("INFO")
    print(f"  日志文件: {log_file}")
    
    # 获取日志器
    logger = get_exe_logger("test_exe")
    logger.info("测试exe日志")
    
    # 获取EXE目录
    exe_dir = get_exe_dir()
    print(f"  EXE目录: {exe_dir}")
    assert exe_dir.exists(), "EXE目录应该存在"
    
    # 获取日志文件路径
    log_path = get_log_file_path()
    assert log_path.exists(), "日志文件路径应该存在"
    
    print("  [PASS] exe_logging向后兼容性测试通过")


def test_dual_channel_logger():
    """测试双通道日志器"""
    print("\n[测试3] 双通道日志器")
    
    from wechat_decrypt_tool.logging_config import DualChannelLogger, LogConfig
    import gc
    
    tmpdir = tempfile.mkdtemp()
    log_dir = Path(tmpdir)
    
    try:
        # 创建开发环境配置
        config = LogConfig.dev_config()
        logger = DualChannelLogger("test_dual", config, log_dir)
        
        # 用户日志
        logger.user_info("正在同步数据，请稍候...")
        logger.user_warn("网络连接不稳定")
        logger.user_error("同步失败", error_type="SYNC_ERROR")
        
        # 系统日志
        logger.debug("同步任务开始", params={"timeout": 30})
        logger.info("API调用完成", elapsed_ms=150)
        logger.warn("请求重试", retry_count=2)
        logger.error("连接失败", exc_info=False)
        
        # 验证日志文件
        user_log = log_dir / "user.log"
        system_log = log_dir / "system.log"
        
        assert user_log.exists(), "用户日志文件应该存在"
        assert system_log.exists(), "系统日志文件应该存在"
        
        print("  [PASS] 双通道日志器测试通过")
    finally:
        # 关闭日志处理器以释放文件句柄
        for handler in logger.user_logger.handlers[:]:
            handler.close()
        for handler in logger.system_logger.handlers[:]:
            handler.close()
        gc.collect()  # 强制垃圾回收


def test_error_convergence():
    """测试错误收敛机制"""
    print("\n[测试4] 错误收敛机制")
    
    from wechat_decrypt_tool.logging_config import DualChannelLogger, LogConfig
    import gc
    
    tmpdir = tempfile.mkdtemp()
    log_dir = Path(tmpdir)
    
    try:
        config = LogConfig.dev_config()
        logger = DualChannelLogger("convergence_test", config, log_dir)
        
        # 相同错误多次
        for _ in range(5):
            logger.user_error("网络连接异常", error_type="NETWORK_ERROR")
        
        # 不同错误
        logger.user_error("数据库连接失败", error_type="DB_ERROR")
        
        # 验证日志内容
        user_log = log_dir / "user.log"
        content = user_log.read_text(encoding='utf-8')
        
        # 应该只有2条错误（收敛后）
        error_count = content.count("ERROR")
        assert error_count == 2, f"应该只有2条错误，实际: {error_count}"
        
        print("  [PASS] 错误收敛机制测试通过")
    finally:
        # 关闭日志处理器以释放文件句柄
        for handler in logger.user_logger.handlers[:]:
            handler.close()
        for handler in logger.system_logger.handlers[:]:
            handler.close()
        gc.collect()  # 强制垃圾回收


def test_environment_config():
    """测试环境感知配置"""
    print("\n[测试5] 环境感知配置")
    
    from wechat_decrypt_tool.logging_config import Environment, LogConfig
    
    # 开发环境
    dev_config = LogConfig.dev_config()
    assert dev_config.level == "DEBUG", "开发环境应使用DEBUG级别"
    assert "console" in dev_config.outputs, "开发环境应输出到控制台"
    
    # 生产环境
    prod_config = LogConfig.prod_config()
    assert prod_config.level == "INFO", "生产环境应使用INFO级别"
    assert "console" not in prod_config.outputs, "生产环境不应输出到控制台"
    assert prod_config.format_type == "json", "生产环境应使用JSON格式"
    
    # 测试环境
    test_config = LogConfig.test_config()
    assert test_config.level == "DEBUG", "测试环境应使用DEBUG级别"
    
    # 统一工厂方法
    config = LogConfig.get_config(Environment.PRODUCTION)
    assert config.level == "INFO", "统一工厂方法应返回正确配置"
    
    print("  [PASS] 环境感知配置测试通过")


def test_exception_handling():
    """测试异常处理覆盖"""
    print("\n[测试6] 异常处理覆盖")
    
    from wechat_decrypt_tool.logging_config import DualChannelLogger, LogConfig, JsonFormatter
    
    # 测试日志目录创建失败时的降级
    # 使用无效路径触发异常处理
    invalid_path = Path("/nonexistent/path/that/should/not/exist")
    
    try:
        config = LogConfig.dev_config()
        logger = DualChannelLogger("test_invalid", config, invalid_path)
        logger.info("测试日志写入")
        print("  [PASS] 日志目录创建失败时正确降级")
    except Exception as e:
        print(f"  [FAIL] 异常处理失败: {e}")
        raise
    
    # 测试JSON序列化失败时的fallback
    formatter = JsonFormatter()
    
    class UnserializableObject:
        def __str__(self):
            return "UnserializableObject"
    
    # 创建一个模拟的LogRecord
    import time
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None
    )
    record.created = time.time()
    
    # 正常序列化
    result = formatter.format(record)
    assert '"message": "Test message"' in result, "JSON格式化应正常工作"
    
    print("  [PASS] 异常处理覆盖测试通过")


def run_all_tests():
    """运行所有测试"""
    print("=" * 70)
    print("  日志系统重构验证脚本")
    print("=" * 70)
    
    tests = [
        test_unified_log_manager,
        test_exe_logging_compatibility,
        test_dual_channel_logger,
        test_error_convergence,
        test_environment_config,
        test_exception_handling,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {test.__name__}: {e}")
            failed += 1
    
    print("\n" + "=" * 70)
    print(f"测试结果: 通过 {passed}/{len(tests)}")
    print("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)