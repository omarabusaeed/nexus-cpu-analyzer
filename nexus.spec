# -*- mode: python ; coding: utf-8 -*-
# NEXUS CPU Analyzer — PyInstaller Build Spec
# Run: pyinstaller nexus.spec

import os

ROOT = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    ['launcher.py'],
    pathex=[ROOT],
    binaries=[],
    datas=[
        # Bundle templates folder
        (os.path.join(ROOT, 'templates'), 'templates'),
        # Bundle static folder (CSS, JS, Chart.js)
        (os.path.join(ROOT, 'static'), 'static'),
    ],
    hiddenimports=[
        'psutil',
        'flask',
        'flask.templating',
        'jinja2',
        'jinja2.ext',
        'werkzeug',
        'werkzeug.serving',
        'werkzeug.routing',
        'werkzeug.exceptions',
        'reportlab',
        'reportlab.pdfgen',
        'reportlab.platypus',
        'reportlab.lib',
        'reportlab.lib.pagesizes',
        'reportlab.lib.colors',
        'reportlab.lib.styles',
        'reportlab.lib.units',
        'reportlab.lib.enums',
        'click',
        'itsdangerous',
        'collections',
        'statistics',
        'csv',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'PIL'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NEXUS_CPU_Analyzer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # Shows a terminal window (good for first version)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='assets/nexus_icon.ico',  # Uncomment if you have an icon file
)

