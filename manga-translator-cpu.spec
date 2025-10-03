# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_binaries
import os

# Collect data files dynamically instead of using a hardcoded path
py3langid_datas = collect_data_files('py3langid')
unidic_datas = collect_data_files('unidic_lite')
manga_ocr_datas = collect_data_files('manga_ocr')  # 收集manga_ocr的数据文件（包括example.jpg）
onnxruntime_datas = collect_data_files('onnxruntime')
onnxruntime_binaries = collect_binaries('onnxruntime')

a = Analysis(
    ['desktop_qt_ui/main.py'],  # 修改为PyQt6版本
    pathex=[],
    binaries=onnxruntime_binaries,
    datas=py3langid_datas + unidic_datas + manga_ocr_datas + onnxruntime_datas,  # 添加manga_ocr和onnxruntime数据文件
    hiddenimports=['pydensecrf.eigen', 'bsdiff4.core', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets'],  # 添加PyQt6隐式导入
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='app',
    debug=True,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='manga-translator-cpu',
)