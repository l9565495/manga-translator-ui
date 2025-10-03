# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_all, get_package_paths
import os

# Collect data files dynamically instead of using a hardcoded path
py3langid_datas = collect_data_files('py3langid')
unidic_datas = collect_data_files('unidic_lite')
manga_ocr_datas = collect_data_files('manga_ocr')  # 收集manga_ocr的数据文件（包括example.jpg）

# 使用collect_all自动收集onnxruntime的所有内容
onnx_datas, onnx_binaries, onnx_hiddenimports = collect_all('onnxruntime')

# 同时将onnxruntime的核心DLL也复制到根目录
onnxruntime_pkg_base, onnxruntime_pkg_dir = get_package_paths('onnxruntime')
onnx_binaries.extend([
    (os.path.join(onnxruntime_pkg_dir, 'capi', 'onnxruntime.dll'), '.'),
    (os.path.join(onnxruntime_pkg_dir, 'capi', 'onnxruntime_providers_shared.dll'), '.'),
])

a = Analysis(
    ['desktop_qt_ui/main.py'],  # 修改为PyQt6版本
    pathex=[],
    binaries=onnx_binaries,
    datas=py3langid_datas + unidic_datas + manga_ocr_datas + onnx_datas,  # 添加所有数据文件
    hiddenimports=['pydensecrf.eigen', 'bsdiff4.core', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets'] + onnx_hiddenimports,  # 添加隐式导入
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.abspath('pyi_rth_onnxruntime.py')],
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