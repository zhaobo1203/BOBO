"""TN-04: SQLCipher 数据库解密模块

功能：
- 使用密钥解密 SQLCipher 数据库
- 支持 session.db、contact.db 等
- 处理 WAL 日志文件
"""

import os
import sqlite3
import tempfile
from pathlib import Path
from typing import List, Dict, Optional

# 导入解密工具
try:
    from wechat_decrypt_tool.wechat_decrypt import WeChatDatabaseDecryptor
except ImportError:
    WeChatDatabaseDecryptor = None


def find_database_files(account_dir: str) -> List[Dict]:
    """查找账号目录下的所有数据库文件

    Args:
        account_dir: 账号数据目录

    Returns:
        list: 数据库文件列表
    """
    db_files = []
    db_storage = os.path.join(account_dir, 'db_storage')

    if not os.path.exists(db_storage):
        return db_files

    # 遍历查找 .db 文件
    for root, dirs, files in os.walk(db_storage):
        for file in files:
            if file.endswith('.db'):
                db_path = os.path.join(root, file)
                # 计算相对路径
                rel_path = os.path.relpath(db_path, db_storage)
                db_files.append({
                    'path': db_path,
                    'name': file,
                    'rel_path': rel_path,
                    'size': os.path.getsize(db_path)
                })

    return db_files


def decrypt_database_to_file(db_key: str, db_path: str, output_path: str = None) -> bool:
    """解密数据库到文件

    Args:
        db_key: 数据库密钥（64位十六进制）
        db_path: 加密的数据库路径
        output_path: 输出路径（可选，默认使用临时文件）

    Returns:
        bool: 是否解密成功
    """
    if WeChatDatabaseDecryptor is None:
        return False

    if not os.path.exists(db_path):
        return False

    if output_path is None:
        output_path = tempfile.mktemp(suffix='.db')

    try:
        decryptor = WeChatDatabaseDecryptor(db_key)
        success = decryptor.decrypt_database(db_path, output_path)
        return success
    except Exception:
        return False


def test_database_decrypt(db_key: str, account_dir: str) -> Dict:
    """测试数据库解密

    Args:
        db_key: 数据库密钥
        account_dir: 账号数据目录

    Returns:
        dict: 包含 success, db_files, decrypted_count 等信息
    """
    result = {
        'success': False,
        'db_files': [],
        'decrypted_count': 0,
        'errors': []
    }

    # 查找数据库文件
    db_files = find_database_files(account_dir)
    result['db_files'] = db_files

    if not db_files:
        result['errors'].append('未找到数据库文件')
        return result

    # 测试解密第一个数据库
    test_db = db_files[0]['path']
    temp_output = tempfile.mktemp(suffix='.db')

    try:
        success = decrypt_database_to_file(db_key, test_db, temp_output)
        if success:
            result['success'] = True
            result['decrypted_count'] = 1

            # 验证数据库
            try:
                conn = sqlite3.connect(temp_output)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()
                result['tables'] = [t[0] for t in tables]
                conn.close()
            except Exception as e:
                result['errors'].append(f'数据库验证失败: {e}')
        else:
            result['errors'].append('解密失败')
    except Exception as e:
        result['errors'].append(f'解密异常: {e}')
    finally:
        # 清理临时文件
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except:
                pass

    return result


# 使用全局字典存储临时文件路径
_temp_db_paths = {}


def get_decrypted_connection(db_key: str, db_path: str) -> Optional[sqlite3.Connection]:
    """获取解密后的数据库连接

    Args:
        db_key: 数据库密钥
        db_path: 数据库路径

    Returns:
        sqlite3.Connection: 数据库连接，失败返回 None
    """
    global _temp_db_paths
    temp_db = tempfile.mktemp(suffix='.db')

    if not decrypt_database_to_file(db_key, db_path, temp_db):
        return None

    try:
        conn = sqlite3.connect(temp_db)
        conn.row_factory = sqlite3.Row
        # 使用全局字典存储临时文件路径
        _temp_db_paths[id(conn)] = temp_db
        return conn
    except Exception:
        if os.path.exists(temp_db):
            os.remove(temp_db)
        return None


def close_decrypted_connection(conn: sqlite3.Connection):
    """关闭解密后的数据库连接并清理临时文件

    Args:
        conn: 数据库连接
    """
    global _temp_db_paths
    if conn:
        temp_path = _temp_db_paths.pop(id(conn), None)
        conn.close()

        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass


def query_decrypted_database(db_key: str, db_path: str, query: str, params: tuple = ()) -> List[Dict]:
    """查询解密后的数据库

    Args:
        db_key: 数据库密钥
        db_path: 数据库路径
        query: SQL 查询语句
        params: 查询参数

    Returns:
        list: 查询结果列表
    """
    conn = get_decrypted_connection(db_key, db_path)
    if not conn:
        return []

    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []
    finally:
        close_decrypted_connection(conn)
