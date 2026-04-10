# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['messages_app.py'],
    pathex=[],
    binaries=[],
    datas=[('icon.png', '.'), ('about.html', '.'), ('about_icon.png', '.')],
    hiddenimports=['win11toast', 'winrt', 'winrt.windows.ui.notifications',
                   'winrt.windows.data.xml.dom', 'winrt.windows.foundation',
                   'winrt.windows.foundation.collections'],
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
    a.binaries,
    a.datas,
    [],
    name='Android Messages Desktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
