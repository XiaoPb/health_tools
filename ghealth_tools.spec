from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_root = Path.cwd()
datas = collect_data_files(
    "health_tools",
    includes=["rules/**/*.yaml", "rules/**/*.yml", "templates/*.pptx"],
)
hiddenimports = collect_submodules("health_tools.commands")

analysis = Analysis(
    [str(project_root / "src" / "health_tools" / "__main__.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PySide6"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

# 不使用 COLLECT，直接生成 PyInstaller onefile 可执行程序。
exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="ghealth-tools-windows-x64",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
