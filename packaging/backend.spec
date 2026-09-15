# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the standalone Windows backend sidecar.

The desktop shell launches this executable with --emit-bootstrap. Keeping the
backend in a sidecar removes the end-user requirement to install Python or keep
a source checkout beside the desktop application.
"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent.parent.resolve()

# These are first-party packages used by the local API/runtime. Explicitly
# collecting them makes dynamically-loaded modules deterministic in release
# builds while PyInstaller still performs its normal static import analysis.
FIRST_PARTY_PACKAGES = [
    "app_api",
    "brain",
    "chat",
    "config",
    "connections",
    "connectors",
    "creative_engine",
    "governance",
    "integrations",
    "knowledge",
    "memory",
    "observability",
    "plugins",
    "runtime",
    "schemas",
    "tools",
    "workspace",
]

hiddenimports = []
datas = []
for package in FIRST_PARTY_PACKAGES:
    hiddenimports += collect_submodules(package)
    datas += collect_data_files(package, include_py_files=False)

analysis = Analysis(
    [str(ROOT / "app_api" / "server.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="ai-marketing-backend",
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
)
