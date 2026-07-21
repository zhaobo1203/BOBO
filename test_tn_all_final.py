#!/usr/bin/env python3
"""
TN-01 ~ TN-06 完整测试脚本
微信数据分析和群消息监听
"""

import sys
import time
import sqlite3
import hashlib
import logging
from pathlib import Path
from datetime import datetime

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from wechat_decrypt_tool.key_store import load_account_keys_store
from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor

# 配置日志
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)

# 全局变量
db_key = None
db_storage = None
account_id = None


def safe_print(text: str):
    """安全打印，处理编码问题"""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode('gbk', errors='replace').decode('gbk'))


def get_msg_table_name(username: str) -> str:
    """根据群ID计算消息表名"""
    md5 = hashlib.md5(username.encode()).hexdigest()
    return f"Msg_{md5}"


def find_message_db_for_group(group_id: str) -> Path:
    """查找包含指定群消息的数据库"""
    table_name = get_msg_table_name(group_id)
    
    for i in range(10):
        msg_db = db_storage / "message" / f"message_{i}.db"
        if not msg_db.exists():
            continue
        
        temp_db = Path(f"temp_find_{i}.db")
        try:
            decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
            decryptor.decrypt_database(str(msg_db), str(temp_db))
            
            conn = sqlite3.connect(str(temp_db))
            cursor = conn.cursor()
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
            result = cursor.fetchone()
            conn.close()
            temp_db.unlink()
            
            if result:
                return msg_db
        except Exception as e:
            if temp_db.exists():
                temp_db.unlink()
    
    return None


def poll_group_messages(group_id: str, group_name: str, interval: float = 5.0, max_rounds: int = 20):
    """轮询群消息"""
    table_name = get_msg_table_name(group_id)
    safe_print(f"\n[监听群] {group_name}")
    safe_print(f"  群ID: {group_id}")
    safe_print(f"  消息表: {table_name}")
    
    # 找到数据库
    msg_db = find_message_db_for_group(group_id)
    if not msg_db:
        safe_print(f"  [错误] 未找到消息数据库")
        return
    
    safe_print(f"  数据库: {msg_db.name}")
    
    last_id = 0
    round_num = 0
    
    while round_num < max_rounds:
        round_num += 1
        safe_print(f"\n[轮询 {round_num}/{max_rounds}] {datetime.now().strftime('%H:%M:%S')}")
        
        try:
            # 解密数据库
            temp_db = Path("temp_poll.db")
            decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
            decryptor.decrypt_database(str(msg_db), str(temp_db))
            
            conn = sqlite3.connect(str(temp_db))
            cursor = conn.cursor()
            
            # 查询新消息
            cursor.execute(f"""
                SELECT 
                    local_id,
                    create_time,
                    message_content,
                    local_type
                FROM {table_name}
                WHERE local_id > ?
                ORDER BY local_id ASC
                LIMIT 50
            """, (last_id,))
            
            messages = cursor.fetchall()
            
            if messages:
                safe_print(f"  发现 {len(messages)} 条新消息:")
                
                for msg in messages:
                    local_id, create_time, content, msg_type = msg
                    
                    # 更新最后ID
                    if local_id > last_id:
                        last_id = local_id
                    
                    # 解析时间
                    if create_time:
                        try:
                            msg_time = datetime.fromtimestamp(create_time).strftime('%H:%M:%S')
                        except:
                            msg_time = "未知时间"
                    else:
                        msg_time = "未知时间"
                    
                    # 消息类型
                    type_names = {
                        1: "文本", 3: "图片", 34: "语音", 
                        43: "视频", 47: "表情", 10000: "系统"
                    }
                    type_name = type_names.get(msg_type, f"类型{msg_type}")
                    
                    # 处理内容
                    if content:
                        if isinstance(content, bytes):
                            try:
                                content = content.decode('utf-8', errors='replace')
                            except:
                                content = "<二进制数据>"
                        content = str(content)
                        if len(content) > 50:
                            content = content[:50] + "..."
                    else:
                        content = "<空>"
                    
                    safe_print(f"    [{msg_time}] [{type_name}] {content}")
            else:
                safe_print("  无新消息")
            
            conn.close()
            temp_db.unlink()
            
        except Exception as e:
            safe_print(f"  [错误] {e}")
        
        if round_num < max_rounds:
            time.sleep(interval)


def main():
    global db_key, db_storage, account_id
    
    print("=" * 60)
    print("TN-01 ~ TN-06 微信数据分析测试")
    print("=" * 60)
    
    # 1. 加载密钥 (TN-03)
    print("\n[TN-03] 加载密钥...")
    key_store = load_account_keys_store()
    if not key_store:
        print("[错误] 未找到密钥存储")
        return
    
    accounts = key_store.get('accounts', {})
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
    
    # 2. 查找数据库路径
    print("\n[TN-04] 查找数据库路径...")
    data_dir = Path("E:/xwechat_files")
    for p in data_dir.glob(f"{account_id}_*/db_storage"):
        db_storage = p
        break
    
    if not db_storage:
        print("[错误] 未找到数据库目录")
        return
    
    print(f"  数据库目录: {db_storage}")
    
    # 3. 获取群聊列表 (TN-06)
    print("\n[TN-06] 获取群聊列表...")
    
    contact_db = db_storage / "contact" / "contact.db"
    temp_db = Path("temp_contact.db")
    
    decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
    decryptor.decrypt_database(str(contact_db), str(temp_db))
    
    conn = sqlite3.connect(str(temp_db))
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT username, nick_name, remark 
        FROM contact 
        WHERE username LIKE '%@chatroom'
        ORDER BY id DESC
        LIMIT 20
    """)
    
    groups = cursor.fetchall()
    conn.close()
    temp_db.unlink()
    
    print(f"  找到 {len(groups)} 个群聊:")
    for i, (username, nick_name, remark) in enumerate(groups):
        display_name = remark or nick_name or username
        safe_name = display_name.encode('gbk', errors='replace').decode('gbk')
        print(f"    {i+1}. {safe_name}")
    
    if not groups:
        print("[错误] 没有找到群聊")
        return
    
    # 选择第一个群进行监听
    group_id = groups[0][0]
    group_name = groups[0][1] or groups[0][0]
    safe_name = group_name.encode('gbk', errors='replace').decode('gbk')
    
    print(f"\n[TN-05] 开始监听群: {safe_name}")
    
    # 开始轮询
    poll_group_messages(
        group_id=group_id,
        group_name=safe_name,
        interval=5.0,
        max_rounds=20
    )
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()