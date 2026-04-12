# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['rust_time_overlay.pyw'],
    pathex=[],
    binaries=[],
    datas=[
        ('icon.ico', '.'),
        ('icon.png', '.'),
    ],
    hiddenimports=[
        'rustplus',
        'rustplus.api',
        'rustplus.api.remote',
        'rustplus.api.remote.rustplus_proto',
        'asyncio',
        'websockets',
        'websockets.legacy',
        'websockets.legacy.client',
        'google.protobuf',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # HTTP/network libs not used by this app
        'requests', 'urllib3', 'certifi', 'charset_normalizer', 'idna',
        # rustplus camera module deps — not used by this app
        'numpy', 'scipy', 'PIL', 'Pillow',
        # other heavy unused packages
        'setuptools', 'pkg_resources', 'distutils',
        'pytest', 'pygments', 'psutil',
        'cryptography',
        'dateutil',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Rust Time Overlay',
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
    icon='icon.ico',
    version='version_info.txt',
)
