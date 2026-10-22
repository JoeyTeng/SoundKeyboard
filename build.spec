import sys
from pathlib import Path

root = Path(SPECPATH)
icon = root / "sound_keyboard.ico"

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(icon), ".")],
    hiddenimports=(
        ["keyboard"]
        if sys.platform == "win32"
        else ["Quartz", "CoreFoundation", "AppKit"]
        if sys.platform == "darwin"
        else []
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["scipy", "matplotlib", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "win32":
    EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="SoundKeyboard",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=str(icon),
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="SoundKeyboard",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        name="SoundKeyboard",
    )
    BUNDLE(
        coll,
        name="SoundKeyboard.app",
        icon=None,
        bundle_identifier="com.pizzadark.soundkeyboard",
        info_plist={"CFBundleName": "SoundKeyboard"},
    )
