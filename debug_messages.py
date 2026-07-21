#!/usr/bin/env python3
"""调试脚本：查看群消息原始内容"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from wechat_decrypt_tool.exe_logging import setup_exe_logging, get_exe_logger
from wechat_decrypt_tool.wechat_waiter import WeChatWaiter
from wechat_decrypt_tool.key_service_retry import KeyAcquisitionService
from wechat_decrypt_tool.wcdb_realtime import open_account, get_messages
from wechat_decrypt_tool.constants import ZSTD_MAGIC

setup_exe_logging()
logger = get_exe_logger(__name__)

def main():
    # 等待微信
    waiter = WeChatWaiter(verbose=True)
    pid = waiter.wait_for_process(timeout=10)
    if not pid:
        print("请先启动微信")
        return
    
    print(f"微信PID: {pid}")
    
    # 获取密钥
    key_service = KeyAcquisitionService(max_retries=1, verbose=True)
    
    # 从存储获取密钥
    import json
    key_file = Path(__file__).parent / 'output' / 'account_keys.json'
    if not key_file.exists():
        print(f"密钥文件不存在: {key_file}")
        return
    
    with open(key_file, 'r', encoding='utf-8') as f:
        store = json.load(f)
    
    if not store:
        print("密钥文件为空")
        return
    
    # 获取第一个账号的密钥
    account_id = list(store.keys())[0]
    db_key = store[account_id]['db_key']
    print(f"账号: {account_id}")
    print(f"密钥: {db_key[:16]}...")
    
    # 查找数据目录
    from wechat_decrypt_tool.wechat_detection import auto_detect_wechat_data_dirs
    data_dirs = auto_detect_wechat_data_dirs()
    if not data_dirs:
        print("未找到数据目录")
        return
    
    data_path = data_dirs[0]
    print(f"数据目录: {data_path}")
    
    # 查找 session.db - 使用正确的账号子目录
    account_dir = Path(data_path) / (account_id + '_a2f9')
    if not account_dir.exists():
        # 尝试查找账号目录
        account_dirs = list(Path(data_path).glob(f'{account_id}*'))
        if account_dirs:
            account_dir = account_dirs[0]
        else:
            print(f"未找到账号目录: {account_id}")
            return
    
    session_db = account_dir / 'db_storage' / 'session' / 'session.db'
    if not session_db.exists():
        print(f"session.db 不存在: {session_db}")
        return
    
    print(f"session.db: {session_db}")
    
    # 打开数据库
    handle = open_account(str(session_db), db_key)
    if not handle:
        print("连接数据库失败")
        return
    
    print(f"数据库连接成功: handle={handle}")
    
    # 获取消息
    group_id = "53109723645@chatroom"  # 市场资讯群
    print(f"\n获取群 {group_id} 的消息...")
    
    messages = get_messages(handle, group_id, limit=10)
    print(f"获取到 {len(messages)} 条消息\n")
    
    for i, msg in enumerate(messages, 1):
        create_time = msg.get('create_time', 0)
        sender = msg.get('sender_username', '未知')
        raw_content = msg.get('message_content', '')
        
        # 解码内容
        if isinstance(raw_content, bytes):
            if raw_content.startswith(ZSTD_MAGIC):
                try:
                    import zstandard as zstd
                    decompressor = zstd.ZstdDecompressor()
                    content = decompressor.decompress(raw_content).decode('utf-8', errors='replace')
                except Exception as e:
                    content = f"[解压失败: {e}]"
            else:
                content = raw_content.decode('utf-8', errors='replace')
        else:
            content = str(raw_content or '')
        
        print(f"=== 消息 {i} ===")
        print(f"时间: {create_time}")
        print(f"发送者: {sender}")
        print(f"内容类型: {type(raw_content).__name__}")
        print(f"内容长度: {len(content)}")
        print(f"内容预览: {content[:200]}")
        print()

if __name__ == '__main__':
    main()