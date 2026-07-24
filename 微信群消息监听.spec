# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置文件
生成单一可执行文件: 微信群消息监听.exe
"""

import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(SPECPATH)

# 分析配置
a = Analysis(
    ['src/main_exe.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        ('src/wechat_decrypt_tool', 'wechat_decrypt_tool'),
    ],
    hiddenimports=[
        'wechat_decrypt_tool',
        'wechat_decrypt_tool.constants',
        'wechat_decrypt_tool.exe_logging',
        'wechat_decrypt_tool.wechat_detection',
        'wechat_decrypt_tool.key_store',
        'wechat_decrypt_tool.key_v4',
        'wechat_decrypt_tool.wechat_decrypt',
        'wechat_decrypt_tool.wcdb_realtime',
        'wechat_decrypt_tool.message_storage',
        'wechat_decrypt_tool.app_paths',
        'wechat_decrypt_tool.logging_config',
        'zstandard',
        'psutil',
        'pymem',
        'pysqlcipher3',
        'sqlite3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'pydoc',
        'doctest',
        'setuptools',
        'pip',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='微信群消息监听_v2.0.0',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)