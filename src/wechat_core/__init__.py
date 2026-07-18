"""微信群消息监听系统 - 核心模块

模块结构：
- process_manager: TN-01 微信进程管理
- account_detector: TN-02 当前登录账号检测
- key_manager: TN-03 密钥获取
- db_decryptor: TN-04 SQLCipher数据库解密
- message_monitor: TN-05/TN-06 消息监听与处理
"""

from .process_manager import (
    detect_wechat_process,
    kill_wechat_processes,
    detect_wechat_installation,
    launch_wechat,
)

from .account_detector import (
    auto_detect_wechat_data_dirs,
    detect_current_logged_in_account,
    extract_account_from_path,
    list_all_accounts,
    get_account_info,
)

from .key_manager import (
    check_wx_key_available,
    fetch_key_via_hook,
    load_key_store,
    save_key_to_store,
    get_account_key,
    get_all_account_keys,
)

from .db_decryptor import (
    find_database_files,
    test_database_decrypt,
    decrypt_database_to_file,
)

from .message_monitor import (
    get_group_messages_from_decrypted_db,
    get_sender_nickname_from_db,
    clean_nickname,
    is_text_message,
    decode_message_content,
    format_timestamp,
    get_group_names,
)

__all__ = [
    # TN-01
    'detect_wechat_process',
    'kill_wechat_processes',
    'detect_wechat_installation',
    'launch_wechat',
    # TN-02
    'auto_detect_wechat_data_dirs',
    'detect_current_logged_in_account',
    'extract_account_from_path',
    'list_all_accounts',
    'get_account_info',
    # TN-03
    'check_wx_key_available',
    'fetch_key_via_hook',
    'load_key_store',
    'save_key_to_store',
    'get_account_key',
    'get_all_account_keys',
    # TN-04
    'find_database_files',
    'test_database_decrypt',
    'decrypt_database_to_file',
    # TN-05/TN-06
    'get_group_messages_from_decrypted_db',
    'get_sender_nickname_from_db',
    'clean_nickname',
    'is_text_message',
    'decode_message_content',
    'format_timestamp',
    'get_group_names',
]
