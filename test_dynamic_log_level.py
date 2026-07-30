#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态日志级别调整功能测试脚本

验证：
1. HealthMonitor - 健康监控器
2. DynamicLogLevelManager - 动态日志级别管理器
3. SamplingHandler - 采样日志处理器
"""

import sys
import time
from pathlib import Path

# 添加src到路径
src_path = Path(__file__).parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from wechat_decrypt_tool.logging_config import (
    HealthMonitor, HealthStatus, DynamicLogLevelManager, 
    SamplingHandler, setup_logging, get_logger
)


def test_health_monitor():
    """测试健康监控器"""
    print("\n[测试1] 健康监控器")
    
    monitor = HealthMonitor()
    
    # 初始状态应该是NORMAL
    assert monitor.check_health() == HealthStatus.NORMAL, "初始状态应为NORMAL"
    print("  初始状态: NORMAL [OK]")
    
    # 记录2次错误（未达阈值）
    for i in range(2):
        triggered = monitor.record_error('key_acquire_fail')
        print(f"  记录错误 {i+1}/2, 触发阈值: {triggered}")
        assert not triggered, f"第{i+1}次不应触发阈值"
    
    # 记录第3次错误（达到阈值）
    triggered = monitor.record_error('key_acquire_fail')
    print(f"  记录错误 3/3, 触发阈值: {triggered}")
    assert triggered, "第3次应该触发阈值"
    
    # 状态应该是ABNORMAL
    assert monitor.check_health() == HealthStatus.ABNORMAL, "状态应为ABNORMAL"
    print("  当前状态: ABNORMAL [OK]")
    
    # 获取异常模块
    abnormal = monitor.get_abnormal_modules()
    print(f"  异常模块: {abnormal}")
    assert 'wechat_core.key' in abnormal, "wechat_core.key应在异常模块中"
    
    # 记录成功，恢复
    monitor.record_success('key_acquire_fail')
    assert monitor.is_module_healthy('wechat_core.key'), "模块应恢复健康"
    print("  模块已恢复: [OK]")
    
    # 重置
    monitor.reset()
    assert monitor.check_health() == HealthStatus.NORMAL, "重置后状态应为NORMAL"
    print("  重置状态: NORMAL [OK]")
    
    print("[PASS] 健康监控器测试通过")


def test_dynamic_log_level_manager():
    """测试动态日志级别管理器"""
    print("\n[测试2] 动态日志级别管理器")
    
    # 初始化日志系统
    setup_logging("INFO")
    logger = get_logger("test_module")
    
    # 创建管理器
    manager = DynamicLogLevelManager()
    
    # 初始状态
    status = manager.get_status()
    print(f"  初始状态: {status}")
    assert status['total_modules'] == 0, "初始应无临时调整"
    
    # 设置临时DEBUG（模块级）
    success = manager.set_temporary_level(
        level='DEBUG',
        module='test_module',
        duration=1,  # 1分钟
        reason='测试触发'
    )
    assert success, "设置临时级别应成功"
    print("  设置临时DEBUG: [OK]")
    
    # 检查状态
    status = manager.get_status()
    print(f"  当前状态: {status}")
    assert status['total_modules'] == 1, "应有1个模块在临时状态"
    assert status['modules_in_debug'][0]['module'] == 'test_module'
    
    # 手动恢复
    manager.restore_level('test_module')
    status = manager.get_status()
    assert status['total_modules'] == 0, "手动恢复后应无临时调整"
    print("  手动恢复: [OK]")
    
    print("[PASS] 动态日志级别管理器测试通过")


def test_health_monitor_integration():
    """测试健康监控器与动态日志管理器集成"""
    print("\n[测试3] 健康监控器与动态日志管理器集成")
    
    # 初始化
    setup_logging("INFO")
    monitor = HealthMonitor()
    manager = DynamicLogLevelManager()
    manager.set_health_monitor(monitor)
    
    print("  模拟密钥获取连续失败3次...")
    for i in range(3):
        triggered = monitor.record_error('key_acquire_fail')
        if triggered:
            print(f"  第{i+1}次失败触发阈值，开启DEBUG")
            manager.set_temporary_level(
                level='DEBUG',
                module='wechat_core.key',
                duration=1,
                reason='密钥获取连续失败≥3次'
            )
    
    # 验证模块在DEBUG状态
    status = manager.get_status()
    print(f"  管理器状态: {status}")
    assert 'wechat_core.key' in [m['module'] for m in status['modules_in_debug']]
    print("  wechat_core.key 模块已开启DEBUG [OK]")
    
    # 模拟恢复
    print("  模拟密钥获取成功...")
    monitor.record_success('key_acquire_fail')
    
    # 检查健康状态
    healthy = monitor.is_module_healthy('wechat_core.key')
    print(f"  模块健康状态: {healthy}")
    assert healthy, "模块应已恢复健康"
    
    print("[PASS] 集成测试通过")


def test_sampling_handler():
    """测试采样日志处理器"""
    print("\n[测试4] 采样日志处理器")
    
    import logging
    from io import StringIO
    
    # 创建字符串缓冲区
    buffer = StringIO()
    handler = logging.StreamHandler(buffer)
    
    # 创建采样处理器（采样率1%，即每100次记录1次）
    sampling = SamplingHandler(
        sample_rate=0.01,
        min_level=logging.INFO,
        target_handler=handler
    )
    
    # 创建测试日志器
    logger = logging.getLogger('sampling_test')
    logger.setLevel(logging.INFO)
    logger.handlers = [sampling]
    
    # 发送100条INFO日志
    for i in range(100):
        logger.info(f"消息 {i}")
    
    # 发送5条ERROR日志（应全量记录）
    for i in range(5):
        logger.error(f"错误 {i}")
    
    # 检查输出
    output = buffer.getvalue()
    lines = [l for l in output.strip().split('\n') if l]
    
    info_count = sum(1 for l in lines if '消息' in l)
    error_count = sum(1 for l in lines if '错误' in l)
    
    print(f"  INFO记录数: {info_count}/100 (采样率1%)")
    print(f"  ERROR记录数: {error_count}/5 (全量)")
    
    assert info_count <= 2, f"INFO应只有1-2条，实际: {info_count}"
    assert error_count == 5, f"ERROR应全量5条，实际: {error_count}"
    
    print("[PASS] 采样日志处理器测试通过")


def run_all_tests():
    """运行所有测试"""
    print("=" * 70)
    print("  动态日志级别调整功能测试")
    print("=" * 70)
    
    tests = [
        test_health_monitor,
        test_dynamic_log_level_manager,
        test_health_monitor_integration,
        test_sampling_handler,
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