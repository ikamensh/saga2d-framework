"""PyInstaller recipe for any saga2d game; saga2d.packaging.build freezes every input first."""
import json
import os
from pathlib import Path
import sys

source = Path(os.environ["SAGA2D_BUILD_SOURCE"])
info = json.loads((source / "release" / "build-info.json").read_text(encoding="utf-8"))
packaging = info["packaging"]
product = info["product"]
a = Analysis(
    [str(source / packaging["entry"])], pathex=[str(source)],
    datas=[(str(source / "saga2d/assets/fonts"), "saga2d/assets/fonts"), (str(source / "release"), "release")],
    hiddenimports=packaging["hiddenimports"],
    excludes=packaging["excludes"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=product, debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=product)
if sys.platform == "darwin":
    app = BUNDLE(coll, name=f"{product}.app", bundle_identifier=packaging["bundle_id"],
                 version=info["version"].partition("-")[0], info_plist={"NSHighResolutionCapable": True})
