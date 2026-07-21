#!/usr/bin/env python3
"""
微信群消息监听系统 - 完整调试脚本
=====================================

此脚本整合了项目的所有功能模块测试，用于：
- 快速验证各模块是否正常工作
- 诊断问题和错误
- 作为开发调试的统一入口

功能模块:
- TN-01: 微信进程管理
- TN-02: 当前登录账号检测
- TN-03: 密钥获取与管理
- TN-04: SQLCipher 数据库解密
- TN-05: WCDB 实时消息监听
- TN-06: 群消息提取与显示

使用方法:
    python debug_all.py                    # 运行完整诊断
    python debug_all.py --quick            # 快速检查（仅检查环境和依赖）
    python debug_all.py --tn01             # 仅测试 TN-01
    python debug_all.py --tn02             # 仅测试 TN-02
    python debug_all.py --tn03             # 仅测试 TN-03
    python debug_all.py --tn04             # 仅测试 TN-04
    python debug_all.py --tn05             # 仅测试 TN-05
    python debug_all.py --tn06             # 仅测试 TN-06
    python debug_all.py --monitor 群名称   # 监听指定群消息
    python debug_all.py --list-groups      # 列出所有群聊
    python debug_all.py --realtime 群名称  # 实时监听群消息
"""

import os
import sys
import time
import argparse
import subprocess
import tempfile
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

# 修复 Windows 控制台编码
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def print_header(title: str):
    """打印标题"""
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def print_subheader(title: str):
    """打印子标题"""
    print()
    print("-" * 40)
    print(title)
    print("-" * 40)


def print_result(name: str, success: bool, message: str = ""):
    """打印结果"""
    status = "[OK]" if success else "[FAIL]"
    print(f"  {status} {name}")
    if message:
        print(f"       {message}")


def safe_print(text: str):
    """安全打印，处理编码问题"""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode('gbk', errors='replace').decode('gbk'))


# ============================================================
# 环境检查
# ============================================================

def check_python_version() -> bool:
    """检查 Python 版本"""
    version = sys.version_info
    if version.major >= 3 and version.minor >= 11:
        print_result("Python 版本", True, f"{version.major}.{version.minor}.{version.micro}")
        return True
    else:
        print_result("Python 版本", False, f"需要 3.11+，当前 {version.major}.{version.minor}.{version.micro}")
        return False


def check_dependencies() -> Dict[str, bool]:
    """检查依赖库"""
    print_subheader("检查依赖库")
    
    dependencies = {
        'cryptography': 'cryptography',
        'psutil': 'psutil',
        'pycryptodome': 'Crypto',
        'loguru': 'loguru',
        'zstandard': 'zstandard',
        'requests': 'requests',
    }
    
    # Windows 特有依赖
    if sys.platform == 'win32':
        dependencies['pywin32'] = 'win32api'
        dependencies['pymem'] = 'pymem'
        dependencies['wx_key'] = 'wx_key'
    
    results = {}
    for name, module in dependencies.items():
        try:
            __import__(module)
            print_result(name, True)
            results[name] = True
        except ImportError as e:
            print_result(name, False, str(e))
            results[name] = False
    
    return results


def check_native_libs() -> Dict[str, bool]:
    """检查原生库"""
    print_subheader("检查原生库")
    
    native_dir = PROJECT_ROOT / "src" / "wechat_decrypt_tool" / "native"
    results = {}
    
    dlls = ['wcdb_api.dll', 'WCDB.dll', 'VoipEngine.dll', 'img_helper.dll']
    for dll in dlls:
        dll_path = native_dir / dll
        exists = dll_path.exists()
        print_result(dll, exists, str(dll_path) if exists else "未找到")
        results[dll] = exists
    
    # 检查 pyd 文件
    pyd_files = list(native_dir.glob("wce_integrity*.pyd"))
    pyd_ok = len(pyd_files) > 0
    print_result("wce_integrity.pyd", pyd_ok, str(pyd_files[0]) if pyd_files else "未找到")
    results['wce_integrity'] = pyd_ok
    
    return results


def check_project_structure() -> bool:
    """检查项目结构"""
    print_subheader("检查项目结构")
    
    required_paths = [
        ("src/wechat_core/__init__.py", True),
        ("src/wechat_core/process_manager.py", True),
        ("src/wechat_core/account_detector.py", True),
        ("src/wechat_core/key_manager.py", True),
        ("src/wechat_core/db_decryptor.py", True),
        ("src/wechat_core/message_monitor.py", True),
        ("src/wechat_main.py", True),
        ("pyproject.toml", True),
        ("key_store.json", False),  # 可选
    ]
    
    all_ok = True
    for path, required in required_paths:
        full_path = PROJECT_ROOT / path
        exists = full_path.exists()
        if exists:
            print_result(path, True)
        elif required:
            print_result(path, False, "必需文件缺失")
            all_ok = False
        else:
            print_result(path, False, "可选文件")
    
    return all_ok


def run_environment_check():
    """运行环境检查"""
    print_header("环境检查")
    
    results = {}
    
    # Python 版本
    results['python'] = check_python_version()
    
    # 依赖库
    results['dependencies'] = check_dependencies()
    
    # 原生库
    results['native'] = check_native_libs()
    
    # 项目结构
    results['structure'] = check_project_structure()
    
    return results


# ============================================================
# TN-01: 微信进程管理
# ============================================================

def test_tn01():
    """测试 TN-01: 微信进程管理"""
    print_header("TN-01: 微信进程管理")
    
    try:
        from wechat_core import (
            detect_wechat_process,
            kill_wechat_processes,
            detect_wechat_installation,
            launch_wechat,
        )
        print_result("模块导入", True)
    except ImportError as e:
        print_result("模块导入", False, str(e))
        return False
    
    # 检测微信进程
    print_subheader("检测微信进程")
    try:
        processes = detect_wechat_process()
        if processes:
            print_result("微信进程", True, f"检测到 {len(processes)} 个进程")
            for proc in processes[:5]:
                print(f"       PID={proc.get('pid')}, EXE={proc.get('exe', 'N/A')[:50]}")
        else:
            print_result("微信进程", False, "未检测到微信进程，请启动微信")
    except Exception as e:
        print_result("微信进程检测", False, str(e))
        return False
    
    # 检测微信安装路径
    print_subheader("检测微信安装路径")
    try:
        install_info = detect_wechat_installation()
        if install_info:
            print_result("微信安装路径", True, install_info.get('wechat_exe_path', 'N/A'))
            print(f"       版本: {install_info.get('version', '未知')}")
        else:
            print_result("微信安装路径", False, "未检测到微信安装")
    except Exception as e:
        print_result("微信安装路径检测", False, str(e))
    
    return True


# ============================================================
# TN-02: 当前登录账号检测
# ============================================================

def test_tn02():
    """测试 TN-02: 当前登录账号检测"""
    print_header("TN-02: 当前登录账号检测")
    
    try:
        from wechat_core import (
            auto_detect_wechat_data_dirs,
            detect_current_logged_in_account,
            list_all_accounts,
            get_account_info,
        )
        print_result("模块导入", True)
    except ImportError as e:
        print_result("模块导入", False, str(e))
        return False
    
    # 检测数据目录
    print_subheader("检测微信数据目录")
    try:
        data_dirs = auto_detect_wechat_data_dirs()
        if data_dirs:
            print_result("数据目录", True, f"检测到 {len(data_dirs)} 个目录")
            for d in data_dirs[:3]:
                print(f"       {d}")
        else:
            print_result("数据目录", False, "未检测到微信数据目录")
    except Exception as e:
        print_result("数据目录检测", False, str(e))
        return False
    
    # 检测当前登录账号
    print_subheader("检测当前登录账号")
    try:
        account = detect_current_logged_in_account()
        if account:
            print_result("当前账号", True)
            print(f"       账号ID: {account.get('current_account')}")
            print(f"       PID: {account.get('pid')}")
        else:
            print_result("当前账号", False, "未检测到登录账号，请确保微信已登录")
    except Exception as e:
        print_result("当前账号检测", False, str(e))
    
    # 列出所有账号
    if data_dirs:
        print_subheader("列出所有账号")
        try:
            accounts = list_all_accounts(data_dirs[0])
            if accounts:
                print_result("账号列表", True, f"共 {len(accounts)} 个账号")
                for acc in accounts[:5]:
                    print(f"       {acc.get('account_id')}: {acc.get('data_path', '')[:50]}")
            else:
                print_result("账号列表", False, "未找到账号")
        except Exception as e:
            print_result("账号列表", False, str(e))
    
    return True


# ============================================================
# TN-03: 密钥管理
# ============================================================

def test_tn03():
    """测试 TN-03: 密钥管理"""
    print_header("TN-03: 密钥管理")
    
    try:
        from wechat_core import (
            check_wx_key_available,
            load_key_store,
            save_key_to_store,
            get_account_key,
            get_all_account_keys,
        )
        print_result("模块导入", True)
    except ImportError as e:
        print_result("模块导入", False, str(e))
        return False
    
    # 检查 wx_key 模块
    print_subheader("检查 wx_key 模块")
    try:
        wx_key_ok = check_wx_key_available()
        print_result("wx_key 模块", wx_key_ok, "可用" if wx_key_ok else "不可用")
    except Exception as e:
        print_result("wx_key 模块检查", False, str(e))
    
    # 加载密钥存储
    print_subheader("加载密钥存储")
    try:
        key_store = load_key_store()
        if key_store:
            accounts = key_store.get('accounts', {})
            print_result("密钥存储", True, f"共 {len(accounts)} 个账号")
            for account_id, info in list(accounts.items())[:5]:
                db_key = info.get('db_key', '')
                key_preview = db_key[:16] + "..." if db_key else "无密钥"
                print(f"       {account_id}: {key_preview}")
        else:
            print_result("密钥存储", False, "未找到密钥存储文件")
    except Exception as e:
        print_result("密钥存储加载", False, str(e))
    
    return True


# ============================================================
# TN-04: 数据库解密
# ============================================================

def test_tn04():
    """测试 TN-04: 数据库解密"""
    print_header("TN-04: 数据库解密")
    
    try:
        from wechat_core import (
            find_database_files,
            test_database_decrypt,
            get_account_key,
            get_account_info,
        )
        from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor
        print_result("模块导入", True)
    except ImportError as e:
        print_result("模块导入", False, str(e))
        return False
    
    # 获取密钥和数据目录
    try:
        from wechat_core import load_key_store, detect_current_logged_in_account, auto_detect_wechat_data_dirs
        from wechat_core.account_detector import get_account_info
    except ImportError:
        pass
    
    # 加载密钥
    key_store = load_key_store() if 'load_key_store' in dir() else None
    if not key_store:
        print_result("密钥存储", False, "请先运行 TN-03 获取密钥")
        return False
    
    accounts = key_store.get('accounts', {})
    if not accounts:
        print_result("账号密钥", False, "没有保存的密钥")
        return False
    
    # 获取第一个有效账号
    account_id = None
    db_key = None
    for acc, info in accounts.items():
        if info.get('db_key'):
            account_id = acc
            db_key = info.get('db_key')
            break
    
    if not db_key:
        print_result("有效密钥", False, "没有有效的密钥")
        return False
    
    print_subheader(f"测试账号: {account_id}")
    print(f"  密钥: {db_key[:16]}...")
    
    # 查找数据库文件
    print_subheader("查找数据库文件")
    data_dirs = auto_detect_wechat_data_dirs() if 'auto_detect_wechat_data_dirs' in dir() else []
    
    db_storage = None
    for data_dir in data_dirs:
        import glob
        matches = glob.glob(str(Path(data_dir) / f"{account_id}_*" / "db_storage"))
        if matches:
            db_storage = Path(matches[0])
            break
    
    if not db_storage:
        # 尝试从 key_store 获取路径
        account_info = accounts.get(account_id, {})
        data_path = account_info.get('data_path', '')
        if data_path:
            db_storage = Path(data_path) / "db_storage" if 'db_storage' not in data_path else Path(data_path)
    
    if not db_storage or not db_storage.exists():
        print_result("数据库目录", False, f"未找到 {account_id} 的数据库目录")
        return False
    
    print_result("数据库目录", True, str(db_storage))
    
    # 测试解密 session.db
    session_db = db_storage / "session" / "session.db"
    if not session_db.exists():
        # 尝试其他路径
        session_db = db_storage / "session.db"
    
    if session_db.exists():
        print_subheader("测试解密 session.db")
        temp_db = tempfile.mktemp(suffix='.db')
        try:
            decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
            success = decryptor.decrypt_database(str(session_db), temp_db)
            if success:
                # 验证解密结果
                conn = sqlite3.connect(temp_db)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()
                conn.close()
                print_result("session.db 解密", True, f"共 {len(tables)} 个表")
            else:
                print_result("session.db 解密", False)
        except Exception as e:
            print_result("session.db 解密", False, str(e))
        finally:
            try:
                os.remove(temp_db)
            except:
                pass
    else:
        print_result("session.db", False, "文件不存在")
    
    # 测试解密 contact.db
    contact_db = db_storage / "contact" / "contact.db"
    if not contact_db.exists():
        contact_db = db_storage / "contact.db"
    
    if contact_db.exists():
        print_subheader("测试解密 contact.db")
        temp_db = tempfile.mktemp(suffix='.db')
        try:
            decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
            success = decryptor.decrypt_database(str(contact_db), temp_db)
            if success:
                conn = sqlite3.connect(temp_db)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM contact WHERE username LIKE '%@chatroom'")
                group_count = cursor.fetchone()[0]
                conn.close()
                print_result("contact.db 解密", True, f"共 {group_count} 个群聊")
            else:
                print_result("contact.db 解密", False)
        except Exception as e:
            print_result("contact.db 解密", False, str(e))
        finally:
            try:
                os.remove(temp_db)
            except:
                pass
    else:
        print_result("contact.db", False, "文件不存在")
    
    return True


# ============================================================
# TN-05: WCDB 实时监听
# ============================================================

def test_tn05():
    """测试 TN-05: WCDB 实时监听"""
    print_header("TN-05: WCDB 实时监听")
    
    try:
        from wechat_decrypt_tool.wcdb_realtime import (
            open_account as wcdb_open_account,
            get_sessions as wcdb_get_sessions,
            get_messages as wcdb_get_messages,
            close_account as wcdb_close_account,
            get_native_logs,
        )
        print_result("模块导入", True)
    except ImportError as e:
        print_result("模块导入", False, str(e))
        return False
    
    # 获取密钥和数据库路径
    from wechat_core import load_key_store, auto_detect_wechat_data_dirs
    import glob
    
    key_store = load_key_store()
    if not key_store:
        print_result("密钥存储", False, "请先运行 TN-03")
        return False
    
    accounts = key_store.get('accounts', {})
    account_id = None
    db_key = None
    
    for acc, info in accounts.items():
        if info.get('db_key'):
            account_id = acc
            db_key = info.get('db_key')
            break
    
    if not db_key:
        print_result("有效密钥", False)
        return False
    
    print_subheader(f"账号: {account_id}")
    print(f"  密钥: {db_key[:16]}...")
    
    # 查找 session.db
    data_dirs = auto_detect_wechat_data_dirs()
    session_db = None
    
    for data_dir in data_dirs:
        matches = glob.glob(str(Path(data_dir) / f"{account_id}_*" / "db_storage" / "session" / "session.db"))
        if matches:
            session_db = Path(matches[0])
            break
    
    if not session_db:
        print_result("session.db", False, "未找到")
        return False
    
    print_result("session.db", True, str(session_db))
    
    # 测试 WCDB 连接
    print_subheader("测试 WCDB 连接")
    print("  正在初始化 WCDB (可能需要几秒)...")
    
    start_time = time.time()
    try:
        handle = wcdb_open_account(str(session_db), db_key)
        elapsed = time.time() - start_time
        
        if handle > 0:
            print_result("WCDB 连接", True, f"handle={handle}, 耗时={elapsed:.2f}s")
            
            # 获取会话列表
            print_subheader("获取会话列表")
            sessions = wcdb_get_sessions(handle)
            groups = [s for s in sessions if s.get('username', '').endswith('@chatroom')]
            print_result("会话列表", True, f"共 {len(sessions)} 个会话，{len(groups)} 个群聊")
            
            for g in groups[:5]:
                print(f"       {g.get('display_name', g.get('username', '未知'))}")
            
            # 获取消息
            if groups:
                print_subheader("获取群消息测试")
                group_id = groups[0].get('username')
                messages = wcdb_get_messages(handle, group_id, limit=5)
                print_result("消息获取", True, f"获取 {len(messages)} 条消息")
                
                for msg in messages[:3]:
                    content = msg.get('message_content', '')
                    if isinstance(content, bytes):
                        content = content.decode('utf-8', errors='replace')
                    sender = msg.get('sender_username', '未知')
                    print(f"       {sender}: {content[:50]}...")
            
            # 关闭连接
            wcdb_close_account(handle)
            print_result("关闭连接", True)
            
        else:
            print_result("WCDB 连接", False, f"handle={handle}")
            
    except Exception as e:
        elapsed = time.time() - start_time
        print_result("WCDB 连接", False, f"耗时={elapsed:.2f}s, 错误={e}")
        return False
    
    # 获取原生日志
    print_subheader("WCDB 原生日志")
    try:
        logs = get_native_logs()
        if logs:
            print_result("原生日志", True, f"共 {len(logs)} 条")
            for log in logs[-3:]:
                print(f"       {log}")
        else:
            print_result("原生日志", True, "无日志")
    except Exception as e:
        print_result("原生日志", False, str(e))
    
    return True


# ============================================================
# TN-06: 群消息提取
# ============================================================

def test_tn06():
    """测试 TN-06: 群消息提取"""
    print_header("TN-06: 群消息提取")
    
    try:
        from wechat_core import (
            get_group_messages_from_decrypted_db,
            get_sender_nickname_from_db,
            get_group_names,
            format_timestamp,
            is_text_message,
        )
        print_result("模块导入", True)
    except ImportError as e:
        print_result("模块导入", False, str(e))
        return False
    
    # 使用已有的测试脚本
    print_subheader("执行完整群消息测试")
    
    test_script = PROJECT_ROOT / "test_tn_all_final.py"
    if test_script.exists():
        print("  运行 test_tn_all_final.py...")
        try:
            result = subprocess.run(
                [sys.executable, str(test_script)],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(PROJECT_ROOT)
            )
            
            if result.returncode == 0:
                print_result("测试脚本", True)
                # 显示部分输出
                lines = result.stdout.split('\n')
                for line in lines[-20:]:
                    if line.strip():
                        safe_print(f"  {line}")
            else:
                print_result("测试脚本", False, result.stderr[:200])
        except subprocess.TimeoutExpired:
            print_result("测试脚本", False, "超时")
        except Exception as e:
            print_result("测试脚本", False, str(e))
    else:
        print_result("测试脚本", False, "test_tn_all_final.py 不存在")
    
    return True


# ============================================================
# 监听群消息
# ============================================================

def monitor_group(group_name: str = None, realtime: bool = False, limit: int = 20):
    """监听群消息"""
    monitor_script = PROJECT_ROOT / "src" / "monitor_group_simple.py"
    
    if not monitor_script.exists():
        print("[错误] monitor_group_simple.py 不存在")
        return
    
    cmd = [sys.executable, str(monitor_script)]
    
    if group_name:
        cmd.extend(["-g", group_name])
        if realtime:
            cmd.append("-r")
        cmd.extend(["-n", str(limit)])
    else:
        cmd.append("--list")
    
    try:
        subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    except KeyboardInterrupt:
        print("\n  监听已停止")


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="微信群消息监听系统 - 完整调试脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python debug_all.py                    # 运行完整诊断
  python debug_all.py --quick            # 快速检查（仅检查环境）
  python debug_all.py --tn01             # 仅测试 TN-01
  python debug_all.py --tn02             # 仅测试 TN-02
  python debug_all.py --tn03             # 仅测试 TN-03
  python debug_all.py --tn04             # 仅测试 TN-04
  python debug_all.py --tn05             # 仅测试 TN-05
  python debug_all.py --tn06             # 仅测试 TN-06
  python debug_all.py --monitor 群名称   # 监听指定群消息
  python debug_all.py --list-groups      # 列出所有群聊
        """
    )
    
    parser.add_argument('--quick', action='store_true', help='快速检查（仅检查环境和依赖）')
    parser.add_argument('--tn01', action='store_true', help='仅测试 TN-01')
    parser.add_argument('--tn02', action='store_true', help='仅测试 TN-02')
    parser.add_argument('--tn03', action='store_true', help='仅测试 TN-03')
    parser.add_argument('--tn04', action='store_true', help='仅测试 TN-04')
    parser.add_argument('--tn05', action='store_true', help='仅测试 TN-05')
    parser.add_argument('--tn06', action='store_true', help='仅测试 TN-06')
    parser.add_argument('--monitor', type=str, metavar='群名称', help='监听指定群消息')
    parser.add_argument('--list-groups', action='store_true', help='列出所有群聊')
    parser.add_argument('--realtime', action='store_true', help='实时监听模式')
    parser.add_argument('--limit', type=int, default=20, help='消息数量限制')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("微信群消息监听系统 - 调试脚本")
    print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 根据参数执行不同测试
    if args.quick:
        run_environment_check()
    elif args.tn01:
        test_tn01()
    elif args.tn02:
        test_tn02()
    elif args.tn03:
        test_tn03()
    elif args.tn04:
        test_tn04()
    elif args.tn05:
        test_tn05()
    elif args.tn06:
        test_tn06()
    elif args.monitor or args.list_groups:
        monitor_group(args.monitor, args.realtime, args.limit)
    else:
        # 运行完整诊断
        print("\n开始完整诊断...\n")
        
        run_environment_check()
        test_tn01()
        test_tn02()
        test_tn03()
        test_tn04()
        test_tn05()
        test_tn06()
        
        print_header("诊断完成")
        print("\n提示:")
        print("  - 如需监听群消息: python debug_all.py --monitor 群名称")
        print("  - 如需实时监听: python debug_all.py --monitor 群名称 --realtime")
        print("  - 如需列出群聊: python debug_all.py --list-groups")


if __name__ == "__main__":
    main()