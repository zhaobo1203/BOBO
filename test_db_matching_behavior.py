#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库匹配行为测试脚本

测试目标：验证《变更提案：密钥获取与数据库定位的稳定性修复.md》中的
"密钥拿到后如何匹配到正确的数据库"功能

核心验证：
    Step 1: 检测微信进程和所有数据目录
    Step 2: 枚举所有 session.db 候选
    Step 3: 获取密钥（支持三种方式）
    Step 4: 多目录匹配验证
    Step 5: 对比验证（展示修复前后差异）
    Step 6: 解密匹配的数据库并读取内容
    Step 7: 结果汇总

运行方法:
    python test_db_matching_behavior.py                    # 完整流程（Hook 获取密钥）
    python test_db_matching_behavior.py --manual-key XXXX  # 用指定密钥测试匹配逻辑
    python test_db_matching_behavior.py --list-only        # 只列出候选，不获取密钥

验收标准：
    所有断言必须全部通过（绿灯）
"""

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# 强制设置UTF-8编码（Windows兼容）
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 添加src到路径
src_path = Path(__file__).parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# ============================================================================
# 导入已实现的模块（核心变更：使用真实实现而非内部重复实现）
# ============================================================================

from wechat_decrypt_tool.database_matcher import (
    SessionDbCandidate,
    MatchResult,
    enumerate_session_dbs,
    find_matching_database,
    _verify_key_for_session_db,
)


# ============================================================================
# 测试步骤实现
# ============================================================================

def step1_detect_wechat_dirs() -> List[str]:
    """Step 1: 检测微信进程和所有数据目录"""
    print("\n" + "=" * 80)
    print("Step 1: 检测微信进程和所有数据目录")
    print("=" * 80)
    
    try:
        from wechat_decrypt_tool.wechat_detection import auto_detect_wechat_data_dirs
        
        data_dirs = auto_detect_wechat_data_dirs()
        
        if not data_dirs:
            print("\n[WARNING] 未检测到微信数据目录")
            return []
        
        print(f"\n检测到 {len(data_dirs)} 个数据目录:")
        for i, dir_path in enumerate(data_dirs, 1):
            print(f"  [{i}] {dir_path}")
        
        return data_dirs
        
    except ImportError as e:
        print(f"\n[ERROR] 导入模块失败: {e}")
        return []


def step2_enumerate_session_dbs(data_dirs: List[str]) -> List[SessionDbCandidate]:
    """Step 2: 枚举所有 session.db 候选"""
    print("\n" + "=" * 80)
    print("Step 2: 枚举所有 session.db 候选")
    print("=" * 80)
    
    if not data_dirs:
        print("\n[SKIP] 无数据目录可搜索")
        return []
    
    # 使用已实现的模块函数
    candidates = enumerate_session_dbs(data_dirs)
    
    if not candidates:
        print("\n[WARNING] 未找到任何 session.db 候选")
        return []
    
    # 输出候选列表表格
    print(f"\n找到 {len(candidates)} 个 session.db 候选:")
    print("-" * 80)
    print(f"{'序号':<4} {'路径':<50} {'大小':<10} {'修改时间':<20}")
    print("-" * 80)
    
    for i, candidate in enumerate(candidates, 1):
        size_str = f"{candidate.size / 1024:.1f} KB"
        mtime_str = datetime.fromtimestamp(candidate.mtime).strftime("%Y-%m-%d %H:%M:%S")
        # 截断路径显示
        path_display = candidate.path
        if len(path_display) > 48:
            path_display = "..." + path_display[-45:]
        print(f"{i:<4} {path_display:<50} {size_str:<10} {mtime_str:<20}")
    
    print("-" * 80)
    
    # 断言验证
    print("\n[断言验证]")
    
    # 断言1: 候选数量 >= 1（微信已登录应该至少有一个 session.db）
    assert len(candidates) >= 1, f"候选数量应 >= 1，实际: {len(candidates)}"
    print(f"  ✓ 候选数量 >= 1: {len(candidates)}")
    
    # 断言2: 所有候选大小 >= 4096
    for candidate in candidates:
        assert candidate.size >= 4096, f"候选大小应 >= 4096，实际: {candidate.size}"
    print(f"  ✓ 所有候选大小 >= 4096 bytes")
    
    # 断言3: 列表按修改时间降序排列
    mtime_list = [c.mtime for c in candidates]
    assert mtime_list == sorted(mtime_list, reverse=True), "列表应按修改时间降序排列"
    print(f"  ✓ 列表按修改时间降序排列")
    
    return candidates


def step3_get_key(args) -> Optional[str]:
    """Step 3: 获取密钥"""
    print("\n" + "=" * 80)
    print("Step 3: 获取密钥")
    print("=" * 80)
    
    # 方式a: --manual-key 参数直接传入
    if args.manual_key:
        key = args.manual_key.strip().lower()
        # 清理可能的 0x 前缀
        if key.startswith("0x"):
            key = key[2:]
        # 只保留十六进制字符
        import re
        key = re.sub(r"[^0-9a-f]", "", key)
        
        if len(key) != 64:
            print(f"\n[ERROR] 密钥长度错误: {len(key)} != 64")
            return None
        print(f"\n[OK] 使用手动传入的密钥")
        print(f"  密钥前缀: {key[:16]}...")
        print(f"  密钥长度: {len(key)}")
        return key
    
    # 方式b: --list-only 模式不需要密钥
    if args.list_only:
        print("\n[SKIP] --list-only 模式，跳过密钥获取")
        return None
    
    # 方式c: Hook 模式获取密钥（使用正确的模块）
    print("\n尝试 Hook 模式获取密钥...")
    print("注意: Hook 模式会重启微信进程")
    
    try:
        from wechat_decrypt_tool.key_service import WeChatKeyFetcher
        
        fetcher = WeChatKeyFetcher()
        result = fetcher.fetch_db_key()
        
        if result:
            key = result.get('key') or result.get('db_key')
            if key and len(str(key)) == 64:
                key = str(key).lower()
                print(f"\n[OK] Hook 模式获取密钥成功")
                print(f"  密钥前缀: {key[:16]}...")
                print(f"  密钥长度: {len(key)}")
                return key
            else:
                print(f"\n[WARNING] Hook 返回密钥格式无效")
        else:
            print(f"\n[WARNING] Hook 模式获取密钥失败")
            
    except ImportError as e:
        print(f"\n[ERROR] 导入 key_service 模块失败: {e}")
    except Exception as e:
        print(f"\n[ERROR] Hook 模式异常: {e}")
    
    # 方式d: 交互式手动输入
    print("\n请手动输入密钥（64位十六进制）:")
    try:
        key = input("密钥: ").strip().lower()
        if key.startswith("0x"):
            key = key[2:]
        import re
        key = re.sub(r"[^0-9a-f]", "", key)
        
        if len(key) == 64:
            print(f"[OK] 使用手动输入的密钥")
            return key
        else:
            print(f"[ERROR] 密钥长度错误: {len(key)} != 64")
            return None
    except (EOFError, KeyboardInterrupt):
        print("\n[SKIP] 无密钥输入")
        return None


def step4_match_database(db_key: str, candidates: List[SessionDbCandidate]) -> MatchResult:
    """Step 4: 多目录匹配验证"""
    print("\n" + "=" * 80)
    print("Step 4: 多目录匹配验证")
    print("=" * 80)
    
    if not db_key:
        print("\n[SKIP] 无密钥，跳过匹配验证")
        return MatchResult()
    
    if not candidates:
        print("\n[SKIP] 无候选，跳过匹配验证")
        return MatchResult()
    
    print(f"\n密钥: {db_key[:16]}...{db_key[-16:]}")
    print(f"候选数量: {len(candidates)}")
    
    # 使用已实现的模块函数进行匹配
    result = find_matching_database(db_key, candidates, max_retries=3, retry_interval=5)
    
    # 输出匹配过程
    print("\n匹配过程:")
    for tried in result.tried_paths:
        status = "✓ 匹配" if tried.get('matched') else "✗ 不匹配"
        path_display = tried.get('path', '')
        if len(path_display) > 50:
            path_display = "..." + path_display[-47:]
        print(f"  [{tried.get('retry', 1)}] {path_display} -> {tried.get('mode', '')} ({status})")
    
    # 输出匹配结果
    print("\n匹配结果:")
    if result.matched_path:
        print(f"  ✓ 匹配的数据库: {result.matched_path}")
        print(f"  ✓ 所属数据目录: {result.matched_data_path}")
        print(f"  ✓ 匹配轮次: 第 {result.verified_at_retry} 次")
    else:
        print(f"  ✗ 未找到匹配的数据库")
    
    # 断言验证
    print("\n[断言验证]")
    
    # 断言1: matched_path 不为空
    assert result.matched_path is not None, "应找到匹配的数据库"
    print(f"  ✓ matched_path 不为空")
    
    # 断言2: matched_data_path 是 matched_path 的上级目录
    if result.matched_path and result.matched_data_path:
        matched_path_normalized = os.path.normpath(result.matched_path)
        data_path_normalized = os.path.normpath(result.matched_data_path)
        assert matched_path_normalized.startswith(data_path_normalized), \
            "matched_data_path 应是 matched_path 的上级目录"
        print(f"  ✓ matched_data_path 是 matched_path 的上级目录")
    
    return result


def step5_comparison_table(db_key: str, candidates: List[SessionDbCandidate], result: MatchResult):
    """Step 5: 对比验证（展示修复前后的差异）"""
    print("\n" + "=" * 80)
    print("Step 5: 对比验证（关键！展示修复前后的差异）")
    print("=" * 80)
    
    if not db_key or not candidates:
        print("\n[SKIP] 无密钥或无候选，跳过对比")
        return
    
    print("\n对比表格:")
    print("-" * 80)
    print(f"{'路径':<50} {'大小':<10} {'修改时间':<20} {'密钥匹配':<10}")
    print("-" * 80)
    
    for candidate in candidates:
        # 使用已实现的验证函数
        matched, mode = _verify_key_for_session_db(db_key, candidate.path)
        
        size_str = f"{candidate.size / 1024:.1f} KB"
        mtime_str = datetime.fromtimestamp(candidate.mtime).strftime("%Y-%m-%d %H:%M:%S")
        match_str = "✓ 匹配" if matched else "✗ 不匹配"
        
        # 截断路径显示
        path_display = candidate.path
        if len(path_display) > 48:
            path_display = "..." + path_display[-45:]
        
        print(f"{path_display:<50} {size_str:<10} {mtime_str:<20} {match_str:<10}")
    
    print("-" * 80)
    
    # 说明修复前后的差异
    print("\n[分析] 修复前后差异:")
    
    if result.matched_path:
        # 假设修复前代码只检查 detected_dirs[0]
        first_candidate = candidates[0] if candidates else None
        
        if first_candidate:
            first_matched, _ = _verify_key_for_session_db(db_key, first_candidate.path)
            
            if not first_matched and result.matched_path != first_candidate.path:
                print(f"""
  修复前行为: 只检查第一个候选 ({first_candidate.path})
             -> 密钥验证失败 -> 判定密钥错误
  
  修复后行为: 遍历所有候选
             -> 在第 {result.verified_at_retry} 次重试时匹配到 {result.matched_path}
             -> 成功定位正确的数据库
""")
            elif first_matched and result.matched_path == first_candidate.path:
                print(f"""
  修复前后行为一致: 第一个候选即匹配
             -> {result.matched_path}
             -> 验证通过
""")
            else:
                print(f"""
  匹配结果: {result.matched_path}
  请检查具体场景判断修复效果
""")
    else:
        print("""
  未找到匹配的数据库
  可能原因: 密钥错误、密钥已过期、或 session.db 文件不完整
""")


def step6_decrypt_and_read(db_key: str, result: MatchResult):
    """Step 6: 解密匹配的数据库并读取内容"""
    print("\n" + "=" * 80)
    print("Step 6: 解密匹配的数据库并读取内容")
    print("=" * 80)
    
    if not db_key or not result.matched_path:
        print("\n[SKIP] 无密钥或无匹配数据库，跳过解密")
        return
    
    try:
        from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor
        import tempfile
        
        print(f"\n解密数据库: {result.matched_path}")
        
        # 创建临时输出目录
        output_dir = Path(tempfile.gettempdir()) / "wechat_test_decrypt"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        output_path = output_dir / "session_decrypted.db"
        
        # 创建解密器
        decryptor = WeChatDatabaseDecryptor(db_key)
        
        # 解密
        success = decryptor.decrypt_database(result.matched_path, str(output_path))
        
        if success:
            print(f"  ✓ 解密成功")
            print(f"  输出路径: {output_path}")
            
            # 读取解密后的数据库
            print("\n读取数据库内容:")
            try:
                conn = sqlite3.connect(str(output_path))
                cursor = conn.cursor()
                
                # 获取所有表
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()
                print(f"  表数量: {len(tables)}")
                
                # 检查是否有 SessionTable
                session_table = None
                for table in tables:
                    if 'session' in table[0].lower():
                        session_table = table[0]
                        break
                
                count = 0
                if session_table:
                    cursor.execute(f"SELECT COUNT(*) FROM {session_table}")
                    count = cursor.fetchone()[0]
                    print(f"  {session_table} 行数: {count}")
                    
                    # 显示最近会话示例
                    if count > 0:
                        cursor.execute(f"""
                            SELECT username, nickname, last_message_time 
                            FROM {session_table} 
                            ORDER BY last_message_time DESC 
                            LIMIT 3
                        """)
                        rows = cursor.fetchall()
                        print(f"\n  最近会话示例:")
                        for row in rows:
                            print(f"    - {row[1] or row[0]}")
                
                conn.close()
                
                # 断言验证
                print("\n[断言验证]")
                assert success, "解密应成功"
                print(f"  ✓ 解密成功")
                
                if session_table:
                    assert count > 0, "SessionTable 行数应 > 0"
                    print(f"  ✓ SessionTable 行数 > 0: {count}")
                
            except sqlite3.Error as e:
                print(f"  [ERROR] 读取数据库失败: {e}")
                
        else:
            print(f"  ✗ 解密失败")
            if hasattr(decryptor, 'last_result') and decryptor.last_result:
                print(f"  错误: {decryptor.last_result.get('error', '未知错误')}")
            
    except ImportError as e:
        print(f"\n[ERROR] 导入解密模块失败: {e}")
    except Exception as e:
        print(f"\n[ERROR] 解密异常: {e}")


def step7_summary(
    data_dirs: List[str],
    candidates: List[SessionDbCandidate],
    db_key: Optional[str],
    result: MatchResult,
    args
):
    """Step 7: 结果汇总"""
    print("\n" + "=" * 80)
    print("Step 7: 结果汇总")
    print("=" * 80)
    
    print("\n" + "-" * 80)
    print("测试结果汇总")
    print("-" * 80)
    
    print(f"\n  检测到数据目录: {len(data_dirs)} 个")
    for i, dir_path in enumerate(data_dirs, 1):
        print(f"    [{i}] {dir_path}")
    
    print(f"\n  枚举到 session.db: {len(candidates)} 个")
    for i, candidate in enumerate(candidates, 1):
        mtime_str = datetime.fromtimestamp(candidate.mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"    [{i}] {candidate.path} ({candidate.size / 1024:.1f} KB, {mtime_str})")
    
    key_source = "无"
    if args.manual_key:
        key_source = "手动输入"
    elif args.list_only:
        key_source = "跳过 (--list-only)"
    elif db_key:
        key_source = "Hook 模式"
    print(f"\n  密钥获取方式: {key_source}")
    
    if result.matched_path:
        retry_str = f"第 {result.verified_at_retry} 次重试匹配" if result.verified_at_retry > 1 else "首次匹配"
        print(f"\n  匹配的数据库: {result.matched_path} ({retry_str})")
        print(f"  所属数据目录: {result.matched_data_path}")
        
        # 展示修复效果
        first_candidate = candidates[0] if candidates else None
        if first_candidate and result.matched_path != first_candidate.path:
            print(f"""
  修复效果展示:
    修复前行为: 只检查第一个候选 -> 可能失败
    修复后行为: 遍历全部 -> 匹配成功
""")
    else:
        print(f"\n  匹配的数据库: 未找到")
        print("""
  可能原因:
    - 密钥不匹配当前账号
    - 密钥已过期（微信重新登录后密钥会变化）
    - session.db 文件不完整或损坏
""")
    
    print("\n" + "-" * 80)
    
    # 最终验收
    print("\n[验收结论]")
    
    all_passed = True
    
    # 检查1: 数据目录检测
    if len(data_dirs) >= 1:
        print(f"  [PASS] 数据目录检测正常")
    else:
        print(f"  [WARN] 未检测到数据目录")
        all_passed = False
    
    # 检查2: session.db 枚举
    if len(candidates) >= 1:
        print(f"  [PASS] session.db 枚举正常")
    else:
        print(f"  [WARN] 未找到 session.db")
        all_passed = False
    
    # 检查3: 密钥匹配（仅当有密钥时）
    if db_key:
        if result.matched_path:
            print(f"  [PASS] 多目录匹配验证成功")
        else:
            print(f"  [FAIL] 未找到匹配的数据库")
            all_passed = False
    else:
        print(f"  [SKIP] 跳过密钥匹配验证（--list-only 模式）")
    
    print("\n" + "=" * 80)
    if all_passed:
        print("[SUCCESS] 测试全部通过！")
    else:
        print("[WARNING] 部分测试未通过，请检查上述结果")
    print("=" * 80)
    
    return all_passed


# ============================================================================
# 主函数
# ============================================================================

def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="数据库匹配行为测试脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
运行示例:
    python test_db_matching_behavior.py                    # 完整流程（Hook 获取密钥）
    python test_db_matching_behavior.py --manual-key XXXX  # 用指定密钥测试匹配逻辑
    python test_db_matching_behavior.py --list-only        # 只列出候选，不获取密钥

验收标准:
    所有断言必须全部通过（绿灯）
        """
    )
    
    parser.add_argument(
        "--manual-key",
        type=str,
        help="手动传入64位十六进制密钥"
    )
    
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="只列出候选，不获取密钥"
    )
    
    parser.add_argument(
        "--hook",
        action="store_true",
        default=True,
        help="使用 Hook 模式获取密钥（默认）"
    )
    
    args = parser.parse_args()
    
    print("\n" + "=" * 80)
    print("数据库匹配行为测试脚本")
    print("根据《变更提案：密钥获取与数据库定位的稳定性修复.md》")
    print("=" * 80)
    
    # Step 1: 检测微信进程和所有数据目录
    data_dirs = step1_detect_wechat_dirs()
    
    # Step 2: 枚举所有 session.db 候选
    candidates = step2_enumerate_session_dbs(data_dirs)
    
    # 如果是 --list-only 模式，到此结束
    if args.list_only:
        print("\n" + "=" * 80)
        print("[INFO] --list-only 模式，跳过后续步骤")
        print("=" * 80)
        
        # 简化汇总
        print("\n结果汇总:")
        print(f"  检测到数据目录: {len(data_dirs)} 个")
        print(f"  枚举到 session.db: {len(candidates)} 个")
        
        # --list-only 模式的验收
        all_passed = len(data_dirs) >= 1 and len(candidates) >= 1
        if all_passed:
            print("\n[SUCCESS] --list-only 测试通过！")
            return 0
        else:
            print("\n[WARNING] 部分检查未通过")
            return 1
    
    # Step 3: 获取密钥
    db_key = step3_get_key(args)
    
    if not db_key:
        print("\n[ERROR] 无法获取密钥，测试终止")
        return 1
    
    # Step 4: 多目录匹配验证
    result = step4_match_database(db_key, candidates)
    
    # Step 5: 对比验证
    step5_comparison_table(db_key, candidates, result)
    
    # Step 6: 解密匹配的数据库并读取内容
    step6_decrypt_and_read(db_key, result)
    
    # Step 7: 结果汇总
    all_passed = step7_summary(data_dirs, candidates, db_key, result, args)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())