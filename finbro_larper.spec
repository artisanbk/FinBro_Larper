# PyInstaller build spec for a single-file FinBro_Larper executable.
#   venv/bin/pip install -r requirements-build.txt
#   venv/bin/pyinstaller --noconfirm --clean finbro_larper.spec      ->  dist/FinBro_Larper (.exe on Windows)
# Build on each OS you want to ship for; PyInstaller can't cross-compile.
import os

from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    [os.path.join(SPECPATH, "run.py")],
    datas=[(os.path.join(SPECPATH, "static"), "static")],  # page + vendored JS, so it runs offline
    # uvicorn imports its protocol/loop/lifespan implementations by name at runtime.
    hiddenimports=collect_submodules("uvicorn"),
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FinBro_Larper",
    console=True,  # the window shows the game's URL; closing it quits the game
    upx=False,
)
