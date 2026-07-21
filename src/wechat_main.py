"""微信群消息监听系统 - 主程序

统一入口，整合 TN-01 ~ TN-06 功能模块

使用方法：
    python wechat_main.py [options]

功能：
    - 检测微信进程和账号
    - 获取/管理数据库密钥
    - 解密数据库
    - 监听群消息
"""

import os
import sys
import argparse
import json
from datetime import datetime
from typing import Dict, List, Optional

# 修复 Windows 控制台 Unicode 编码问题
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入核心模块
from wechat_core import (
    # TN-01
    detect_wechat_process,
    kill_wechat_processes,
    detect_wechat_installation,
    launch_wechat,
    # TN-02
    auto_detect_wechat_data_dirs,
    detect_current_logged_in_account,
    list_all_accounts,
    get_account_info,
    # TN-03
    check_wx_key_available,
    load_key_store,
    save_key_to_store,
    get_account_key,
    get_all_account_keys,
    # TN-04
    find_database_files,
    test_database_decrypt,
    # TN-05/TN-06
    get_group_messages_from_decrypted_db,
    get_sender_nickname_from_db,
    get_group_names,
    format_timestamp,
    is_text_message,
)


# ============== TN-01: 进程管理 ==============

def get_wechat_processes() -> List[Dict]:
    """获取微信进程列表

    Returns:
        list: 进程列表
    """
    return detect_wechat_process()


def get_wechat_install_path() -> Optional[str]:
    """获取微信安装路径

    Returns:
        str: 安装路径，失败返回 None
    """
    info = detect_wechat_installation()
    return info.get('wechat_exe_path')


# ============== TN-02: 账号检测 ==============

def get_current_account() -> Optional[Dict]:
    """获取当前登录账号

    Returns:
        dict: 包含 account_id, pid 的字典
    """
    result = detect_current_logged_in_account()
    if result:
        return {
            'account_id': result['current_account'],
            'pid': result['pid']
        }
    return None


def get_all_accounts(data_dir: str = None) -> List[Dict]:
    """获取所有账号列表

    Args:
        data_dir: 数据目录（可选）

    Returns:
        list: 账号列表
    """
    return list_all_accounts(data_dir)


def get_account_data_path(account_id: str) -> Optional[str]:
    """获取账号数据路径

    Args:
        account_id: 账号ID

    Returns:
        str: 数据路径
    """
    info = get_account_info(account_id)
    if info:
        return info['data_path']
    return None


# ============== TN-03: 密钥管理 ==============

def get_saved_keys() -> Dict:
    """获取已保存的密钥

    Returns:
        dict: 账号ID到密钥的映射
    """
    return get_all_account_keys()


def has_key(account_id: str) -> bool:
    """检查账号是否有密钥

    Args:
        account_id: 账号ID

    Returns:
        bool: 是否有密钥
    """
    return get_account_key(account_id) is not None


def save_key(account_id: str, db_key: str, nickname: str = None) -> bool:
    """保存账号密钥

    Args:
        account_id: 账号ID
        db_key: 数据库密钥
        nickname: 昵称（可选）

    Returns:
        bool: 是否成功
    """
    return save_key_to_store(account_id, db_key, nickname)


# ============== TN-04: 数据库解密 ==============

def get_database_list(account_dir: str) -> List[Dict]:
    """获取数据库文件列表

    Args:
        account_dir: 账号数据目录

    Returns:
        list: 数据库文件列表
    """
    return find_database_files(account_dir)


def test_decrypt(account_id: str) -> Dict:
    """测试账号数据库解密

    Args:
        account_id: 账号ID

    Returns:
        dict: 包含 success, tables, errors 的结果
    """
    db_key = get_account_key(account_id)
    if not db_key:
        return {'success': False, 'errors': ['未找到密钥']}

    account_dir = get_account_data_path(account_id)
    if not account_dir:
        return {'success': False, 'errors': ['未找到账号目录']}

    return test_database_decrypt(db_key, account_dir)


# ============== TN-05/TN-06: 群消息处理 ==============

def get_all_groups(account_id: str) -> Dict[str, str]:
    """获取所有群聊

    Args:
        account_id: 账号ID

    Returns:
        dict: 群ID到群名称的映射
    """
    db_key = get_account_key(account_id)
    if not db_key:
        return {}

    account_dir = get_account_data_path(account_id)
    if not account_dir:
        return {}

    return get_group_names(db_key, account_dir)


def get_group_messages(account_id: str, group_id: str, limit: int = 100) -> List[Dict]:
    """获取群消息

    Args:
        account_id: 账号ID
        group_id: 群ID
        limit: 消息数量限制

    Returns:
        list: 消息列表
    """
    db_key = get_account_key(account_id)
    if not db_key:
        return []

    account_dir = get_account_data_path(account_id)
    if not account_dir:
        return []

    return get_group_messages_from_decrypted_db(db_key, account_dir, group_id, limit)


def get_text_messages(account_id: str, group_id: str, limit: int = 100) -> List[Dict]:
    """获取群文字消息

    Args:
        account_id: 账号ID
        group_id: 群ID
        limit: 消息数量限制

    Returns:
        list: 文字消息列表
    """
    messages = get_group_messages(account_id, group_id, limit)
    return [m for m in messages if m.get('is_text')]


def get_sender_name(account_id: str, sender_id: str) -> str:
    """获取发送者昵称

    Args:
        account_id: 账号ID
        sender_id: 发送者ID

    Returns:
        str: 昵称
    """
    db_key = get_account_key(account_id)
    if not db_key:
        return "未知"

    account_dir = get_account_data_path(account_id)
    if not account_dir:
        return "未知"

    return get_sender_nickname_from_db(db_key, account_dir, sender_id)


# ============== 输出格式化 ==============

def print_header(title: str):
    """打印标题"""
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def format_message(msg: Dict, account_id: str) -> str:
    """格式化消息输出

    Args:
        msg: 消息字典
        account_id: 账号ID

    Returns:
        str: 格式化后的消息
    """
    time_str = format_timestamp(msg.get('create_time'))
    sender = get_sender_name(account_id, msg.get('sender_username', ''))
    content = msg.get('content', '')

    if len(content) > 100:
        content = content[:100] + '...'

    return f"[{time_str}] {sender}: {content}"


# ============== 运行模式 ==============

def run_full_test():
    """运行完整测试流程"""
    print_header("微信群消息监听系统 - 完整测试")
    print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # TN-01
    print_header("TN-01: 微信进程管理")
    processes = get_wechat_processes()
    print(f"检测到 {len(processes)} 个微信进程")
    for proc in processes:
        print(f"  PID: {proc['pid']}, EXE: {proc['exe']}")

    install_path = get_wechat_install_path()
    print(f"微信安装路径: {install_path or '未检测到'}")

    # TN-02
    print_header("TN-02: 当前登录账号检测")
    current = get_current_account()
    if current:
        print(f"当前登录账号: {current['account_id']}")
        print(f"进程 PID: {current['pid']}")
    else:
        print("未检测到当前登录账号")

    data_dirs = auto_detect_wechat_data_dirs()
    print(f"检测到 {len(data_dirs)} 个数据目录")

    if data_dirs:
        accounts = get_all_accounts(data_dirs[0])
        print(f"找到 {len(accounts)} 个账号")
        for acc in accounts[:5]:
            print(f"  {acc['account_id']}: {acc['data_path']}")

    # TN-03
    print_header("TN-03: 密钥管理")
    saved_keys = get_saved_keys()
    print(f"已有 {len(saved_keys)} 个账号的密钥")
    for account_id in list(saved_keys.keys())[:3]:
        print(f"  {account_id}")

    wx_key_ok = check_wx_key_available()
    print(f"wx-key 模块: {'可用' if wx_key_ok else '不可用'}")

    # TN-04
    print_header("TN-04: 数据库解密测试")
    if current and saved_keys:
        account_id = current['account_id']
        result = test_decrypt(account_id)
        if result['success']:
            print(f"解密成功，表: {result.get('tables', [])}")
        else:
            print(f"解密失败: {result.get('errors', [])}")
    else:
        print("跳过解密测试")

    # TN-05/TN-06
    print_header("TN-05/TN-06: 群消息测试")
    if current and saved_keys:
        account_id = current['account_id']
        groups = get_all_groups(account_id)
        print(f"找到 {len(groups)} 个群聊")

        if groups:
            first_group_id = list(groups.keys())[0]
            first_group_name = groups[first_group_id]

            print(f"\n测试群聊: {first_group_name}")
            print(f"群ID: {first_group_id}")
            print("-" * 40)

            messages = get_text_messages(account_id, first_group_id, 10)
            print(f"文字消息: {len(messages)} 条")

            for msg in messages[:5]:
                print(f"  {format_message(msg, account_id)}")
    else:
        print("跳过消息测试")

    print_header("测试完成")


def run_monitor_mode(group_id: str = None, limit: int = 20):
    """运行监听模式"""
    print_header("群消息监听模式")

    current = get_current_account()
    if not current:
        print("错误: 未检测到当前登录账号")
        return

    account_id = current['account_id']
    print(f"当前账号: {account_id}")

    if not has_key(account_id):
        print("错误: 未找到账号密钥")
        return

    groups = get_all_groups(account_id)
    print(f"找到 {len(groups)} 个群聊")

    if not group_id:
        print("\n群聊列表:")
        for i, (gid, gname) in enumerate(groups.items()):
            print(f"  {i+1}. {gname} ({gid})")
        return

    print(f"\n监听群: {groups.get(group_id, group_id)}")
    print(f"群ID: {group_id}")
    print("-" * 40)

    messages = get_text_messages(account_id, group_id, limit)
    for msg in reversed(messages):
        print(format_message(msg, account_id))


def run_export_mode(group_id: str, output: str = None):
    """运行导出模式"""
    current = get_current_account()
    if not current:
        print("错误: 未检测到当前登录账号")
        return

    account_id = current['account_id']

    if not has_key(account_id):
        print("错误: 未找到账号密钥")
        return

    messages = get_text_messages(account_id, group_id, 1000)

    if not messages:
        print("未找到消息")
        return

    # 格式化输出
    output_data = []
    for msg in messages:
        output_data.append({
            'time': format_timestamp(msg.get('create_time')),
            'sender': get_sender_name(account_id, msg.get('sender_username', '')),
            'content': msg.get('content', '')
        })

    if output:
        with open(output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"已导出 {len(output_data)} 条消息到 {output}")
    else:
        print(json.dumps(output_data, indent=2, ensure_ascii=False))


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='微信群消息监听系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python wechat_main.py                         # 运行完整测试
  python wechat_main.py --monitor               # 列出所有群聊
  python wechat_main.py --monitor --group ID    # 监听指定群
  python wechat_main.py --export --group ID     # 导出群消息
        """
    )

    parser.add_argument('--monitor', action='store_true', help='监听模式')
    parser.add_argument('--export', action='store_true', help='导出模式')
    parser.add_argument('--group', type=str, help='群ID')
    parser.add_argument('--limit', type=int, default=20, help='消息数量限制')
    parser.add_argument('--output', type=str, help='输出文件路径')
    parser.add_argument('--test', action='store_true', help='运行完整测试')

    args = parser.parse_args()

    if args.export:
        if not args.group:
            print("错误: 导出模式需要指定 --group")
            return
        run_export_mode(args.group, args.output)
    elif args.monitor:
        run_monitor_mode(args.group, args.limit)
    else:
        run_full_test()


if __name__ == '__main__':
    main()
