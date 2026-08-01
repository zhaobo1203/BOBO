# -*- mode: python ; coding: utf-8 -*-
"""
微信群消息监听与股票分析系统 v3.0.0 - PyInstaller 打包配置文件

配置说明:
- 打包模式: 单文件打包 (onefile)
- 入口文件: src/main.py（统一入口）
- 输出名称: 微信群小工具_v3.0.0.exe
- 包含模块: 模块1(微信监控) + 模块2(A股数据管理) + 模块3(股票分析)
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

# Native DLL 文件（模块1必需）
native_dll_patterns = [
    'src/wechat_decrypt_tool/native/*.dll',
    'src/wechat_decrypt_tool/native/*.pyd',
]

# WASM/JS 文件（模块1必需）
wasm_patterns = [
    'src/wechat_decrypt_tool/native/weflow_wasm/*',
]

# A股数据库（首次释放用）
# 注意：按"绝对干净"原则，不打包本地数据库文件
# 首次运行时由代码自动创建表结构，数据通过API手动更新
a_stock_db_pattern = 'data/a_stock_db/a_stock.db'

# 黑名单配置（模块3必需）
blacklist_pattern = 'src/stock_analysis/config/blacklist.json'

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
                filtered_datas.append((full_path, dest))

# 收集 Native DLL
collect_files(native_dll_patterns, 'wechat_decrypt_tool/native')

# 收集 WASM/JS 文件
collect_files(wasm_patterns, 'wechat_decrypt_tool/native/weflow_wasm')

# 收集 A股数据库（已禁用 - 按"绝对干净"原则，不打包本地数据
# 首次运行时由 AStockDatabase._init_database() 自动创建表结构，
# 用户通过 POST /api/update-stock-db 接口手动更新A股数据）
# a_stock_db_path = os.path.join(PROJECT_ROOT, a_stock_db_pattern)
# if os.path.exists(a_stock_db_path):
#     filtered_datas.append((a_stock_db_path, 'data/a_stock_db'))
# else:
#     print(f"[警告] A股数据库不存在: {a_stock_db_path}")
print("[信息] 按干净打包原则，A股数据库不打包，首次运行自动创建表结构")

# 收集黑名单配置
blacklist_path = os.path.join(PROJECT_ROOT, blacklist_pattern)
if os.path.exists(blacklist_path):
    filtered_datas.append((blacklist_path, 'stock_analysis/config'))
else:
    print(f"[警告] 黑名单配置不存在: {blacklist_path}")

# ============== 隐式导入模块 ==============

# --- 模块1（手动列出，已验证）---
hiddenimports_m1 = [
    # 标准库
    'sqlite3', 'winreg', 'ctypes', 'ctypes.wintypes',
    'multiprocessing', 'multiprocessing.freeze_support',
    'concurrent', 'concurrent.futures', 'concurrent.futures.thread',
    'threading', 'queue', 'socket', 'hashlib', 'hmac', 'struct',
    'json', 're', 'logging', 'logging.handlers', 'datetime',
    'pathlib', 'tempfile', 'shutil', 'typing', 'dataclasses',
    'collections', 'functools', 'itertools', 'warnings',

    # 第三方库 - 进程管理
    'psutil', 'psutil._pswindows', 'psutil._common',

    # 第三方库 - 内存读取 (Windows only)
    'pymem', 'pymem.exception', 'pymem.memory', 'pymem.process',
    'pymem.ressources', 'pymem.ressources.structure',

    # 第三方库 - 加密
    'Crypto', 'Crypto.Cipher', 'Crypto.Cipher.AES',
    'Crypto.Protocol', 'Crypto.Protocol.KDF',
    'Crypto.Hash', 'Crypto.Hash.SHA512', 'Crypto.Hash.SHA256',
    'Crypto.Random', 'Crypto.Util', 'Crypto.Util.Padding',
    'cryptography', 'cryptography.hazmat', 'cryptography.hazmat.backends',
    'cryptography.hazmat.backends.default_backend',
    'cryptography.hazmat.primitives', 'cryptography.hazmat.primitives.ciphers',
    'cryptography.hazmat.primitives.ciphers.algorithms',
    'cryptography.hazmat.primitives.ciphers.modes',

    # 第三方库 - 压缩
    'zstandard',

    # 第三方库 - 密钥提取
    'wx_key',

    # 内部模块 - wechat_decrypt_tool 包
    'wechat_decrypt_tool',
    'wechat_decrypt_tool.api', 'wechat_decrypt_tool.app_paths',
    'wechat_decrypt_tool.avatar_cache', 'wechat_decrypt_tool.chat_accounts',
    'wechat_decrypt_tool.chat_edit_store', 'wechat_decrypt_tool.chat_export_service',
    'wechat_decrypt_tool.chat_helpers', 'wechat_decrypt_tool.chat_realtime_autosync',
    'wechat_decrypt_tool.chat_realtime_reader', 'wechat_decrypt_tool.chat_search_index',
    'wechat_decrypt_tool.constants', 'wechat_decrypt_tool.database_filters',
    'wechat_decrypt_tool.dll_key_scan', 'wechat_decrypt_tool.exe_logging',
    'wechat_decrypt_tool.export_integrity', 'wechat_decrypt_tool.img_helper',
    'wechat_decrypt_tool.isaac64', 'wechat_decrypt_tool.key_bruteforce',
    'wechat_decrypt_tool.key_service', 'wechat_decrypt_tool.key_service_retry',
    'wechat_decrypt_tool.key_store', 'wechat_decrypt_tool.key_v4',
    'wechat_decrypt_tool.logging_config', 'wechat_decrypt_tool.media_helpers',
    'wechat_decrypt_tool.message_storage', 'wechat_decrypt_tool.network_access',
    'wechat_decrypt_tool.path_fix', 'wechat_decrypt_tool.perf_trace',
    'wechat_decrypt_tool.request_logging', 'wechat_decrypt_tool.runtime_settings',
    'wechat_decrypt_tool.session_last_message', 'wechat_decrypt_tool.sns_export_service',
    'wechat_decrypt_tool.sns_media', 'wechat_decrypt_tool.sns_realtime_autosync',
    'wechat_decrypt_tool.source_fallback', 'wechat_decrypt_tool.sqlite_diagnostics',
    'wechat_decrypt_tool.wcdb_realtime', 'wechat_decrypt_tool.wechat_decrypt',
    'wechat_decrypt_tool.wechat_detection', 'wechat_decrypt_tool.wechat_waiter',
    'wechat_decrypt_tool.xlsx_export',

    # 内部模块 - MCP
    'wechat_decrypt_tool.mcp', 'wechat_decrypt_tool.mcp.errors',
    'wechat_decrypt_tool.mcp.protocol', 'wechat_decrypt_tool.mcp.registry',
    'wechat_decrypt_tool.mcp.tools',

    # 内部模块 - Routers
    'wechat_decrypt_tool.routers',
    'wechat_decrypt_tool.routers.account_archive_export',
    'wechat_decrypt_tool.routers.admin', 'wechat_decrypt_tool.routers.biz',
    'wechat_decrypt_tool.routers.chat_contacts', 'wechat_decrypt_tool.routers.chat_export',
    'wechat_decrypt_tool.routers.chat_media', 'wechat_decrypt_tool.routers.chat',
    'wechat_decrypt_tool.routers.decrypt', 'wechat_decrypt_tool.routers.favorites',
    'wechat_decrypt_tool.routers.general', 'wechat_decrypt_tool.routers.group_monitor',
    'wechat_decrypt_tool.routers.health', 'wechat_decrypt_tool.routers.import_decrypted',
    'wechat_decrypt_tool.routers.keys', 'wechat_decrypt_tool.routers.mcp',
    'wechat_decrypt_tool.routers.media', 'wechat_decrypt_tool.routers.record_export',
    'wechat_decrypt_tool.routers.sns_export', 'wechat_decrypt_tool.routers.sns',
    'wechat_decrypt_tool.routers.system', 'wechat_decrypt_tool.routers.wechat_detection',
    'wechat_decrypt_tool.routers.wrapped',

    # 内部模块 - Wrapped
    'wechat_decrypt_tool.wrapped', 'wechat_decrypt_tool.wrapped.service',
    'wechat_decrypt_tool.wrapped.storage', 'wechat_decrypt_tool.wrapped.cards',

    # 内部模块 - wechat_core
    'wechat_core', 'wechat_core.account_detector', 'wechat_core.db_decryptor',
    'wechat_core.key_manager', 'wechat_core.message_monitor', 'wechat_core.process_manager',
]

# --- 模块2/3新增（自动收集）---
hiddenimports_m2_auto = []
hiddenimports_m3_auto = []

try:
    hiddenimports_m3_auto += collect_submodules('fastapi')
    hiddenimports_m3_auto += collect_submodules('uvicorn')
    hiddenimports_m3_auto += collect_submodules('uvicorn.lifespan')
    hiddenimports_m3_auto += collect_submodules('uvicorn.protocols')
    hiddenimports_m3_auto += collect_submodules('uvicorn.logging')
except Exception as e:
    print(f"[警告] 自动收集FastAPI/uvicorn子模块失败: {e}")

try:
    hiddenimports_m2_auto += collect_submodules('akshare')
except Exception as e:
    print(f"[警告] 自动收集akshare子模块失败: {e}")

try:
    hiddenimports_m2_auto += collect_submodules('baostock')
except Exception as e:
    print(f"[警告] 自动收集baostock子模块失败: {e}")

try:
    hiddenimports_m2_auto += collect_submodules('efinance')
except Exception as e:
    print(f"[警告] 自动收集efinance子模块失败: {e}")

# --- 模块2/3内部模块（手动列出）---
hiddenimports_m2_m3_manual = [
    # 模块2 - a_stock_db
    'a_stock_db', 'a_stock_db.data_sources', 'a_stock_db.database',

    # 模块3 - stock_analysis
    'stock_analysis', 'stock_analysis.main', 'stock_analysis.dashboard',
    'stock_analysis.config', 'stock_analysis.config.settings',
    'stock_analysis.api', 'stock_analysis.api.routes',
    'stock_analysis.models', 'stock_analysis.models.mention', 'stock_analysis.models.stock',
    'stock_analysis.services', 'stock_analysis.services.matcher',
    'stock_analysis.services.statistics', 'stock_analysis.services.stock_loader',
    'stock_analysis.services.storage',

    # 模块3新增第三方库
    'jieba',
    'pypinyin',
    'loguru',
    'httpx', 'httpx._transports', 'httpx._transports.default',
    'anyio', 'anyio._backends',
    'starlette', 'starlette.routing', 'starlette.middleware',
]

# 合并所有隐式导入
all_hiddenimports = hiddenimports_m1 + hiddenimports_m2_auto + hiddenimports_m3_auto + hiddenimports_m2_m3_manual

# 去重
all_hiddenimports = list(dict.fromkeys(all_hiddenimports))

# ============== 排除模块 ==============
excludes_list = [
    'tkinter', 'matplotlib', 'PIL',
    'cv2', 'torch', 'tensorflow', 'scipy',
    'IPython', 'jupyter', 'pytest', 'sphinx',
]
# 注意：akshare间接依赖pandas/numpy，运行时需要，不排除
# 如果打包后akshare功能异常，需要从排除列表中移除pandas/numpy

# ============== 分析配置 ==============
a = Analysis(
    ['src/main.py'],
    pathex=[PROJECT_ROOT, os.path.join(PROJECT_ROOT, 'src')],
    binaries=[],
    datas=filtered_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes_list,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='微信群小工具_v3.0.0',
    debug=False,
    bootloader_ignore_signals=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='x64',
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    uac_admin=False,
    upx=False,
)
