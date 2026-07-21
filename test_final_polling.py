#!/usr/bin/env python3
"""
TN-05/06 最终轮询监听方案
直接解密数据库并轮询群消息
"""

import sys
import time
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent / "src"))

from wechat_decrypt_tool.key_store import load_account_keys_store
from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor


def get_msg_table_name(username: str) -> str:
    """根据群ID计算消息表名"""
    md5 = hashlib.md5(username.encode()).hexdigest()
    return f"Msg_{md5}"


def find_message_db(db_storage: Path, table_name: str) -> Path:
    """查找包含指定表的消息数据库"""
    for i in range(6):  # message_0.db 到 message_5.db
        msg_db = db_storage / "message" / f"message_{i}.db"
        if msg_db.exists():
            # 解密并检查表是否存在
            temp_db = Path(f"temp_check_{i}.db")
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

    return None


def poll_group_messages(
    db_storage: Path,
    db_key: str,
    group_id: str,
    interval: float = 3.0,
    max_rounds: int = 10
):
    """轮询群消息"""

    # 计算消息表名
    table_name = get_msg_table_name(group_id)
    print(f"\n群ID: {group_id}")
    print(f"消息表: {table_name}")

    # 找到包含该表的消息数据库
    msg_db = find_message_db(db_storage, table_name)
    if not msg_db:
        print(f"[错误] 未找到包含表 {table_name} 的数据库")
        return

    print(f"数据库: {msg_db}")

    # 轮询
    last_sort_seq = 0
    round_num = 0

    while round_num < max_rounds:
        round_num += 1
        print(f"\n[轮询 {round_num}/{max_rounds}] {datetime.now().strftime('%H:%M:%S')}")

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
                WHERE sort_seq > ?
                ORDER BY sort_seq ASC
                LIMIT 20
            """, (last_sort_seq,))

            messages = cursor.fetchall()

            if messages:
                print(f"  发现 {len(messages)} 条新消息:")
                for msg in messages:
                    local_id, create_time, content, msg_type = msg

                    # 解析时间
                    if create_time:
                        msg_time = datetime.fromtimestamp(create_time).strftime('%H:%M:%S')
                    else:
                        msg_time = "未知时间"

                    # 截取内容
                    if content and len(content) > 60:
                        content = content[:60] + "..."

                    # 消息类型
                    type_names = {1: "文本", 3: "图片", 34: "语音", 43: "视频", 47: "表情", 10000: "系统"}
                    type_name = type_names.get(msg_type, f"类型{msg_type}")

                    print(f"    [{msg_time}] [{type_name}] {content}")

                # 更新最后的位置
                # 获取最新的 sort_seq
                cursor.execute(f"SELECT MAX(local_id) FROM {table_name}")
                last_sort_seq = cursor.fetchone()[0] or 0
            else:
                print("  无新消息")

            conn.close()
            temp_db.unlink()

        except Exception as e:
            print(f"  [错误] {e}")

        if round_num < max_rounds:
            print(f"  等待 {interval} 秒...")
            time.sleep(interval)


# 全局变量
db_key = None


def main():
    global db_key

    print("=" * 60)
    print("TN-05/06 轮询监听测试")
    print("=" * 60)

    # 1. 加载密钥
    print("\n[1] 加载密钥...")
    key_store = load_account_keys_store()
    if not key_store:
        print("[错误] 未找到密钥存储")
        return

    accounts = key_store.get('accounts', {})

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

    # 2. 查找数据库路径
    print("\n[2] 查找数据库路径...")
    data_dir = Path("E:/xwechat_files")
    db_storage = None
    for p in data_dir.glob(f"{account_id}_*/db_storage"):
        db_storage = p
        break

    if not db_storage:
        print("[错误] 未找到数据库目录")
        return

    print(f"  数据库目录: {db_storage}")

    # 3. 获取群聊列表
    print("\n[3] 获取群聊列表...")

    contact_db = db_storage / "contact" / "contact.db"
    temp_db = Path("temp_contact_list.db")

    decryptor = WeChatDatabaseDecryptor(key_hex=db_key)
    decryptor.decrypt_database(str(contact_db), str(temp_db))

    conn = sqlite3.connect(str(temp_db))
    cursor = conn.cursor()

    cursor.execute("""
        SELECT username, nick_name, remark
        FROM contact
        WHERE username LIKE '%@chatroom'
        ORDER BY id DESC
        LIMIT 15
    """)

    groups = cursor.fetchall()
    conn.close()
    temp_db.unlink()

    print(f"  找到 {len(groups)} 个群聊:")
    for i, (username, nick_name, remark) in enumerate(groups):
        display_name = remark or nick_name or username
        # 过滤非ASCII字符以避免编码问题
        safe_name = display_name.encode('gbk', errors='replace').decode('gbk')
        print(f"    {i+1}. {safe_name} ({username})")

    if not groups:
        print("[错误] 没有找到群聊")
        return

    # 选择第一个群
    group_id = groups[0][0]
    group_name = groups[0][1] or groups[0][0]

    print(f"\n[4] 开始轮询群: {group_name}")

    # 4. 开始轮询
    poll_group_messages(
        db_storage=db_storage,
        db_key=db_key,
        group_id=group_id,
        interval=3.0,
        max_rounds=10
    )


if __name__ == "__main__":
    main()
