"""
测试 message_*.db 解密查询新逻辑: 遍历 -> 收集 -> 排序 -> 截取
测试目标: 群名称 "AI测试群"
流程: 自动检测微信 → 获取密钥 → 解密 → 遍历所有分片 → 收集全部消息 → 全局排序 → 截取最新N条
"""

import os
import sys
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime

# 添加 src 到路径
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor
from wechat_decrypt_tool.chat_helpers import _iter_message_db_paths, _resolve_msg_table_name_by_map
from wechat_core import (
    detect_wechat_process,
    auto_detect_wechat_data_dirs,
    get_account_key,
    load_key_store,
    get_group_names,
)

ZSTD_MAGIC = b'(\xb5/\xfd'


def get_group_id_by_name(account_dir: Path, db_key: bytes, temp_dir: str, target_group_name: str) -> str | None:
    """根据群名称查找群ID"""
    # 解密 contact.db
    contact_db_path = account_dir / "contact.db"
    if not contact_db_path.exists():
        print(f"[-] contact.db 不存在: {contact_db_path}")
        return None

    temp_contact = os.path.join(temp_dir, "contact_test.db")
    decryptor = WeChatDatabaseDecryptor(db_key)
    if not decryptor.decrypt_database(str(contact_db_path), temp_contact):
        print(f"[-] 解密 contact.db 失败")
        return None

    try:
        conn = sqlite3.connect(temp_contact)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 查询群聊
        cursor.execute("""
            SELECT username, nickname 
            FROM rcontact 
            WHERE type = 2 AND nickname LIKE ?
        """, (f"%{target_group_name}%",))

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            print(f"[-] 未找到包含 '{target_group_name}' 的群聊")
            return None

        if len(rows) > 1:
            print(f"\n找到多个匹配:")
            for i, row in enumerate(rows):
                print(f"  {i+1}. {row['nickname']} (username: {row['username']})")
            # 默认取第一个
            row = rows[0]
        else:
            row = rows[0]

        print(f"[+] 找到目标群: {row['nickname']} (username: {row['username']})")
        return row['username']

    except Exception as e:
        print(f"[-] 查询 contact.db 失败: {e}")
        return None


def collect_messages_from_all_dbs(
    account_dir: Path,
    db_key: bytes,
    temp_dir: str,
    group_id: str,
) -> list[dict]:
    """
    严格按照新逻辑执行:
    1. 遍历 -> 2. 收集 -> 3. 排序 -> 4. 截取
    """
    # Step 1: 遍历所有符合条件的 message_*.db 分片
    db_paths = _iter_message_db_paths(account_dir)
    print(f"\n[+] 遍历结果: 找到 {len(db_paths)} 个 message 数据库分片")
    for p in db_paths:
        print(f"  - {p.name}")

    # Step 2: 收集全部消息（遍历所有分片，不提前终止）
    all_messages: list[dict] = []
    decryptor = WeChatDatabaseDecryptor(db_key)

    for idx, db_path in enumerate(db_paths, 1):
        temp_db = os.path.join(temp_dir, f"message_{idx}.db")

        try:
            # 解密当前分片
            if not decryptor.decrypt_database(str(db_path), temp_db):
                print(f"  [warning] 解密 {db_path.name} 失败，跳过")
                continue

            # 连接解密后的数据库
            conn = sqlite3.connect(temp_db)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 获取所有表名
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0].lower() for row in cursor.fetchall()]

            # 解析消息表名
            table_name = _resolve_msg_table_name_by_map(
                {t: t for t in tables}, group_id)

            if not table_name:
                print(f"  [warning] {db_path.name} 中未找到群消息表，跳过")
                conn.close()
                continue

            # 查询该分片所有该群消息
            cursor.execute(f"""
                SELECT localId, createTime, content, talker
                FROM {table_name}
                WHERE talker = ?
            """, (group_id,))

            rows = cursor.fetchall()
            collected = 0

            for row in rows:
                try:
                    content = row['content']
                    create_time = row['createTime'] or 0

                    # 处理 zstd 压缩
                    if isinstance(content, bytes):
                        if content.startswith(ZSTD_MAGIC):
                            import zstandard as zstd
                            decompressor = zstd.ZstdDecompressor()
                            try:
                                content = decompressor.decompress(content).decode('utf-8')
                            except Exception:
                                content = str(content)
                        else:
                            content = content.decode('utf-8', errors='replace')

                    all_messages.append({
                        'local_id': row['localId'],
                        'create_time': create_time,
                        'content': content or '',
                        'sender': row['talker'],
                        'db_name': db_path.name
                    })
                    collected += 1
                except Exception as e:
                    continue

            conn.close()
            print(f"  [+] {db_path.name}: 收集到 {collected} 条消息")

        except Exception as e:
            print(f"  [-] 处理 {db_path.name} 异常: {e}")
            continue

        # 删除临时文件
        try:
            os.remove(temp_db)
        except:
            pass

    print(f"\n[+] 收集完成: 总共收集到 {len(all_messages)} 条消息")
    return all_messages


def main():
    target_group_name = "AI测试群"
    limit = 50  # 截取最后 50 条最新消息

    print("=" * 60)
    print("测试 message_*.db 新逻辑: 遍历 -> 收集 -> 排序 -> 截取")
    print(f"目标群: {target_group_name}")
    print("=" * 60)

    # Step 0: 创建临时目录
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"\n[+] 临时目录: {temp_dir}")

        # Step 1: 检测微信进程
        print("\n[+] 检测微信进程...")
        processes = detect_wechat_process()
        if not processes:
            print("[-] 未找到运行中的微信进程，请先启动微信")
            sys.exit(1)
        # 取第一个进程
        wechat_process = processes[0]
        print(f"[+] 找到微信进程 (PID: {wechat_process['pid']})")

        # Step 2: 获取数据目录和账号
        print("\n[+] 查找账号目录...")
        data_dirs = auto_detect_wechat_data_dirs()
        if not data_dirs:
            print("[-] 未找到微信数据目录")
            sys.exit(1)
        
        # 找第一个有密钥的账号
        account_dir = None
        db_key = None
        for data_dir in data_dirs:
            accounts = list(Path(data_dir).iterdir())
            for acc_dir in accounts:
                if not acc_dir.is_dir():
                    continue
                found_key = get_account_key(acc_dir.name)
                if found_key:
                    account_dir = acc_dir
                    db_key = bytes.fromhex(found_key)
                    break
                if account_dir:
                    break
        
        if not account_dir or not db_key:
            print("[-] 未找到已提取密钥的账号")
            sys.exit(1)
        
        print(f"[+] 使用账号目录: {account_dir}")
        print(f"[+] 密钥加载成功，长度: {len(db_key)} 字节")

        # Step 4: 根据名称查找群ID
        print("\n[+] 查找目标群...")
        group_id = get_group_id_by_name(account_dir, db_key, temp_dir, target_group_name)
        if not group_id:
            sys.exit(1)

        # Step 5: 严格按照新逻辑执行 - 遍历 -> 收集 -> 排序 -> 截取
        print("\n[+] 开始执行新逻辑测试...")
        all_messages = collect_messages_from_all_dbs(
            account_dir, db_key, temp_dir, group_id)

        if not all_messages:
            print("\n[-] 未收集到任何消息")
            sys.exit(1)

        # Step 3: 排序 - 按 create_time 升序排序（最新消息在最后）
        print(f"\n[+] Step 3: 全局排序（按时间戳）")
        all_messages.sort(key=lambda x: x['create_time'])
        print(f"[+] 排序完成")

        # Step 4: 截取 - 获取最后 limit 条最新消息
        print(f"\n[+] Step 4: 截取最新 {limit} 条消息")
        latest_messages = all_messages[-limit:] if len(all_messages) > limit else all_messages
        print(f"[+] 截取完成，共 {len(latest_messages)} 条消息")

        # Step 5: 输出结果
        print("\n" + "=" * 60)
        print(f"最新 {len(latest_messages)} 条消息:")
        print("=" * 60)

        for i, msg in enumerate(latest_messages, 1):
            dt = datetime.fromtimestamp(msg['create_time'])
            content_preview = str(msg['content'])[:80]
            if len(str(msg['content'])) > 80:
                content_preview += "..."
            print(f"\n{i:3d}. [{dt}] <来自 {msg['db_name']}>")
            print(f"     {content_preview}")

        print("\n" + "=" * 60)
        print("[+] 测试完成!")
        print(f"统计: 遍历 {len(list(_iter_message_db_paths(account_dir)))} DB | "
              f"收集 {len(all_messages)} 条 | 截取 {len(latest_messages)} 条最新消息")
        print("=" * 60)


if __name__ == "__main__":
    main()