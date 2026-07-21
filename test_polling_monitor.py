#!/usr/bin/env python3
"""
TN-05/06 轮询监听方案 - 直接读取数据库文件
不依赖 WCDB sidecar，直接使用 SQLCipher 解密
"""

import sys
import time
import sqlite3
from pathlib import Path
from datetime import datetime

# 添加 src 目录到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from wechat_decrypt_tool.key_store import load_account_keys_store
from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor

def poll_group_messages(
    session_db_path: str,
    db_key: str,
    group_id: str,
    limit: int = 10,
    interval: float = 2.0,
    max_rounds: int = 5
):
    """
    轮询群消息
    
    Args:
        session_db_path: session.db 文件路径
        db_key: 数据库密钥 (64位十六进制)
        group_id: 群ID (如 12345678@chatroom)
        limit: 每次获取的消息数量
        interval: 轮询间隔（秒）
        max_rounds: 最大轮询次数
    """
    print(f"\n{'='*60}")
    print(f"轮询监听群消息")
    print(f"群ID: {group_id}")
    print(f"轮询间隔: {interval}秒")
    print(f"{'='*60}\n")
    
    # 解密数据库
    print("[1] 解密 session.db...")
    temp_db = Path("temp_session_decrypted.db")
    try:
        # 使用 WeChatDatabaseDecryptor 解密
        decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
        success = decryptor.decrypt_database(str(session_db_path), str(temp_db))
        if not success:
            print(f"  [错误] 解密失败")
            return
        print(f"  [OK] 数据库解密成功")
    except Exception as e:
        print(f"  [错误] 解密失败: {e}")
        return
    
    # 轮询消息
    last_create_time = 0
    round_num = 0
    
    while round_num < max_rounds:
        round_num += 1
        print(f"\n[轮询 {round_num}/{max_rounds}] {datetime.now().strftime('%H:%M:%S')}")
        
        try:
            # 读取解密后的数据库
            conn = sqlite3.connect(str(temp_db))
            cursor = conn.cursor()
            
            # 查询新消息
            cursor.execute("""
                SELECT 
                    localId,
                    createTime,
                    talker,
                    sender_username,
                    message_content,
                    message_type
                FROM SessionMessage
                WHERE talker = ? AND createTime > ?
                ORDER BY createTime DESC
                LIMIT ?
            """, (group_id, last_create_time, limit))
            
            messages = cursor.fetchall()
            
            if messages:
                print(f"  发现 {len(messages)} 条新消息:")
                for msg in reversed(messages):  # 按时间正序显示
                    local_id, create_time, talker, sender, content, msg_type = msg
                    last_create_time = max(last_create_time, create_time)
                    
                    # 解析时间
                    msg_time = datetime.fromtimestamp(create_time / 1000).strftime('%H:%M:%S')
                    
                    # 截取内容
                    if content and len(content) > 50:
                        content = content[:50] + "..."
                    
                    print(f"    [{msg_time}] {sender or '未知'}: {content}")
            else:
                print("  无新消息")
            
            conn.close()
            
        except Exception as e:
            print(f"  [错误] 查询失败: {e}")
        
        if round_num < max_rounds:
            print(f"  等待 {interval} 秒...")
            time.sleep(interval)
    
    # 清理临时文件
    if temp_db.exists():
        temp_db.unlink()
        print(f"\n[清理] 已删除临时文件: {temp_db}")


def main():
    print("=" * 60)
    print("TN-05/06 轮询监听测试")
    print("=" * 60)
    
    # 1. 加载密钥
    print("\n[准备] 加载密钥...")
    key_store = load_account_keys_store()
    if not key_store:
        print("[错误] 未找到密钥存储")
        return
    
    accounts = key_store.get('accounts', {})
    
    # 选择第一个有密钥的账号
    account_id = None
    db_key = None
    for acc, info in accounts.items():
        if info.get('db_key'):
            account_id = acc
            db_key = info.get('db_key')
            break
    
    if not db_key:
        print("[错误] 没有找到有效的密钥")
        return
    
    print(f"  账号: {account_id}")
    print(f"  密钥: {db_key[:16]}...")
    
    # 2. 查找数据库
    print("\n[准备] 查找数据库...")
    data_dir = Path("E:/xwechat_files")
    session_db = None
    
    for p in data_dir.glob(f"{account_id}_*/db_storage/session/session.db"):
        session_db = p
        break
    
    if not session_db:
        print("[错误] 未找到 session.db")
        return
    
    print(f"  session.db: {session_db}")
    
    # 3. 获取群聊列表
    print("\n[准备] 获取群聊列表...")
    temp_db = Path("temp_session_decrypted.db")
    try:
        decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
        success = decryptor.decrypt_database(str(session_db), str(temp_db))
        if not success:
            print("[错误] 解密失败")
            return
        
        conn = sqlite3.connect(str(temp_db))
        cursor = conn.cursor()
        
        # 获取群聊列表
        cursor.execute("""
            SELECT talker, displayName 
            FROM SessionTable 
            WHERE talker LIKE '%@chatroom'
            ORDER BY updateTime DESC
            LIMIT 20
        """)
        
        groups = cursor.fetchall()
        print(f"  找到 {len(groups)} 个群聊:")
        for i, (talker, name) in enumerate(groups):
            print(f"    {i+1}. {name or talker} ({talker})")
        
        conn.close()
        temp_db.unlink()
        
        if not groups:
            print("[错误] 没有找到群聊")
            return
        
        # 选择第一个群
        group_id = groups[0][0]
        group_name = groups[0][1] or group_id
        
        print(f"\n[选择] 监听群: {group_name}")
        
        # 4. 开始轮询
        poll_group_messages(
            session_db_path=str(session_db),
            db_key=db_key,
            group_id=group_id,
            limit=10,
            interval=2.0,
            max_rounds=10
        )
        
    except Exception as e:
        print(f"[错误] {e}")
        import traceback
        traceback.print_exc()
        if temp_db.exists():
            temp_db.unlink()


if __name__ == "__main__":
    main()