# -*- mode: python ; coding: utf-8 -*-
"""
微信群消息监听系统 - PyInstaller 打包配置文件

配置说明:
- 打包模式: 单文件打包 (onefile)
- 入口文件: src/simple_monitor.py
- 输出名称: 微信群消息监听.exe
- 控制台模式: 启用 (console=True)
- UPX压缩: 禁用 (保证兼容性)
"""

import os
import sys
import glob
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# 获取项目根目录
PROJECT_ROOT = os.path.dirname(os.path.abspath(SPEC))

# ============== 数据文件收集 ==============
# Native DLL 文件（必需）
native_dll_patterns = [
    'src/wechat_decrypt_tool/native/*.dll',
    'src/wechat_decrypt_tool/native/*.pyd',
]

# 收集所有数据文件
filtered_datas = []

def collect_files(patterns, dest):
    """收集匹配的文件到目标目录"""
    for pattern in patterns:
        if '*' in pattern:
            matches = glob.glob(os.path.join(PROJECT_ROOT, pattern))
            for match in matches:
                filtered_datas.append((match, dest))
        else:
            full_path = os.path.join(PROJECT_ROOT, pattern)
            if os.path.exists(full_path):
                filtered_datas.append((pattern, dest))

# 收集 Native DLL（不包含 WASM 视频解码文件）
collect_files(native_dll_patterns, 'wechat_decrypt_tool/native')

# ============== 隐式导入模块 ==============
hiddenimports = [
    # 标准库
    'sqlite3',
    'winreg',
    'ctypes',
    'ctypes.wintypes',
    'multiprocessing',
    'multiprocessing.freeze_support',
    'concurrent',
    'concurrent.futures',
    'concurrent.futures.thread',
    'threading',
    'queue',
    'socket',
    'hashlib',
    'hmac',
    'struct',
    'json',
    're',
    'logging',
    'logging.handlers',
    'datetime',
    'pathlib',
    'tempfile',
    'shutil',
    'typing',
    'dataclasses',
    'collections',
    'functools',
    'itertools',
    'warnings',
    
    # 第三方库 - 进程管理
    'psutil',
    'psutil._pswindows',
    'psutil._common',
    
    # 第三方库 - 内存读取 (Windows only)
    'pymem',
    'pymem.exception',
    'pymem.memory',
    'pymem.process',
    'pymem.ressources',
    'pymem.ressources.structure',
    
    # 第三方库 - 加密
    'Crypto',
    'Crypto.Cipher',
    'Crypto.Cipher.AES',
    'Crypto.Protocol',
    'Crypto.Protocol.KDF',
    'Crypto.Hash',
    'Crypto.Hash.SHA512',
    'Crypto.Hash.SHA256',
    'Crypto.Random',
    'Crypto.Util',
    'Crypto.Util.Padding',
    'cryptography',
    'cryptography.hazmat',
    'cryptography.hazmat.backends',
    'cryptography.hazmat.backends.default_backend',
    'cryptography.hazmat.primitives',
    'cryptography.hazmat.primitives.ciphers',
    'cryptography.hazmat.primitives.ciphers.algorithms',
    'cryptography.hazmat.primitives.ciphers.modes',
    
    # 第三方库 - 压缩
    'zstandard',
    
    # 第三方库 - 密钥提取
    'wx_key',
    
    # 内部模块 - wechat_decrypt_tool 包
    'wechat_decrypt_tool',
    'wechat_decrypt_tool.api',
    'wechat_decrypt_tool.app_paths',
    'wechat_decrypt_tool.avatar_cache',
    'wechat_decrypt_tool.chat_accounts',
    'wechat_decrypt_tool.chat_edit_store',
    'wechat_decrypt_tool.chat_export_service',
    'wechat_decrypt_tool.chat_helpers',
    'wechat_decrypt_tool.chat_realtime_autosync',
    'wechat_decrypt_tool.chat_realtime_reader',
    'wechat_decrypt_tool.chat_search_index',
    'wechat_decrypt_tool.constants',
    'wechat_decrypt_tool.database_filters',
    'wechat_decrypt_tool.dll_key_scan',
    'wechat_decrypt_tool.exe_logging',
    'wechat_decrypt_tool.export_integrity',
    'wechat_decrypt_tool.img_helper',
    'wechat_decrypt_tool.isaac64',
    'wechat_decrypt_tool.key_bruteforce',
    'wechat_decrypt_tool.key_service',
    'wechat_decrypt_tool.key_store',
    'wechat_decrypt_tool.key_v4',
    'wechat_decrypt_tool.logging_config',
    'wechat_decrypt_tool.media_helpers',
    'wechat_decrypt_tool.message_storage',
    'wechat_decrypt_tool.network_access',
    'wechat_decrypt_tool.path_fix',
    'wechat_decrypt_tool.perf_trace',
    'wechat_decrypt_tool.request_logging',
    'wechat_decrypt_tool.runtime_settings',
    'wechat_decrypt_tool.session_last_message',
    'wechat_decrypt_tool.sns_export_service',
    'wechat_decrypt_tool.sns_media',
    'wechat_decrypt_tool.sns_realtime_autosync',
    'wechat_decrypt_tool.source_fallback',
    'wechat_decrypt_tool.sqlite_diagnostics',
    'wechat_decrypt_tool.wcdb_realtime',
    'wechat_decrypt_tool.wechat_decrypt',
    'wechat_decrypt_tool.wechat_detection',
    'wechat_decrypt_tool.xlsx_export',
    
    # 内部模块 - MCP
    'wechat_decrypt_tool.mcp',
    'wechat_decrypt_tool.mcp.errors',
    'wechat_decrypt_tool.mcp.protocol',
    'wechat_decrypt_tool.mcp.registry',
    'wechat_decrypt_tool.mcp.tools',
    
    # 内部模块 - Routers
    'wechat_decrypt_tool.routers',
    'wechat_decrypt_tool.routers.account_archive_export',
    'wechat_decrypt_tool.routers.admin',
    'wechat_decrypt_tool.routers.biz',
    'wechat_decrypt_tool.routers.chat_contacts',
    'wechat_decrypt_tool.routers.chat_export',
    'wechat_decrypt_tool.routers.chat_media',
    'wechat_decrypt_tool.routers.chat',
    'wechat_decrypt_tool.routers.decrypt',
    'wechat_decrypt_tool.routers.favorites',
    'wechat_decrypt_tool.routers.general',
    'wechat_decrypt_tool.routers.group_monitor',
    'wechat_decrypt_tool.routers.health',
    'wechat_decrypt_tool.routers.import_decrypted',
    'wechat_decrypt_tool.routers.keys',
    'wechat_decrypt_tool.routers.mcp',
    'wechat_decrypt_tool.routers.media',
    'wechat_decrypt_tool.routers.record_export',
    'wechat_decrypt_tool.routers.sns_export',
    'wechat_decrypt_tool.routers.sns',
    'wechat_decrypt_tool.routers.system',
    'wechat_decrypt_tool.routers.wechat_detection',
    'wechat_decrypt_tool.routers.wrapped',
    
    # 内部模块 - Wrapped
    'wechat_decrypt_tool.wrapped',
    'wechat_decrypt_tool.wrapped.service',
    'wechat_decrypt_tool.wrapped.storage',
    'wechat_decrypt_tool.wrapped.cards',
]

# ============== 分析配置 ==============
a = Analysis(
    ['src/simple_monitor.py'],
    pathex=[PROJECT_ROOT, os.path.join(PROJECT_ROOT, 'src')],
    binaries=[],
    datas=filtered_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除明确不需要的大型第三方库
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'PIL',
        'cv2',
        'torch',
        'tensorflow',
        'scipy',
        'IPython',
        'jupyter',
        'pytest',
        'sphinx',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='微信群消息监听',
    debug=False,
    bootloader_ignore_signals=False,
    runtime_tmpdir=None,
    console=True,  # 控制台程序，显示详细错误信息
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可以添加图标: icon='assets/icon.ico'
    uac_admin=False,  # 不强制管理员权限，兼容性更好
    upx=False,  # 禁用UPX压缩，保证兼容性
)