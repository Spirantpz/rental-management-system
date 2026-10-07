# PyInstaller spec: one-folder (onedir) build.  Build with:  pyinstaller RentalManagement.spec --noconfirm
a = Analysis(
    ["run.py"],
    pathex=["."],
    datas=[("app/templates", "app/templates"),
           ("app/static", "app/static"),
           ("app/schema.sql", "app")],
    hiddenimports=["scripts.reset_db", "scripts.seed_demo", "scripts.init_db"],
    excludes=["tkinter", "pytest", "unittest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="RentalManagement", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="RentalManagement")
