# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

# プロジェクトのルートディレクトリ
project_root = Path('.')

block_cipher = None

# アセットファイルの収集
added_files = [
    (str(project_root / 'src/assets/icon/icon.ico'), 'assets/icon/'),
    (str(project_root / 'src/assets/icon/icon.gif'), 'assets/icon/'),
]

a = Analysis(
    ['src\\main.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=added_files,
    hiddenimports=[
        'librosa',
        'sounddevice', 
        'pythonosc',
        'customtkinter',
        'matplotlib',
        'numpy',
        'scipy',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SnoreGuard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # ウィンドウアプリケーションなのでFalse
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / 'src/assets/icon/icon.ico'),  # 実行ファイルのアイコン
)
