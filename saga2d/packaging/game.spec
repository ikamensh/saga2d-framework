"""PyInstaller recipe for any saga2d game; saga2d.packaging.build freezes every input first."""
import json
import os
from pathlib import Path
import sys

source = Path(os.environ["SAGA2D_BUILD_SOURCE"])
info = json.loads((source / "release" / "build-info.json").read_text(encoding="utf-8"))
packaging = info["packaging"]
product = info["product"]
# Every snapshotted package ships its ``assets`` folder beside its code: the
# engine's fonts, a game's committed art and sound pieces. Modules find it as
# ``Path(__file__).parent / "assets"`` in the frozen tree exactly as in a checkout.
datas = [(str(source / "release"), "release")]
for name in ("saga2d", "sagaforge", packaging["package"]):
    assets = source / name / "assets"
    if assets.is_dir():
        datas.append((str(assets), f"{name}/assets"))
a = Analysis(
    [str(source / packaging["entry"])], pathex=[str(source)],
    datas=datas,
    hiddenimports=packaging["hiddenimports"],
    excludes=packaging["excludes"],
)
pyz = PYZ(a.pure)
# The build wrote the platform's icon beside this recipe: an .ico inside the
# Windows executable, an .icns in the Mac bundle, nothing elsewhere.
icon = str(source / packaging["icon"]) if packaging["icon"] else None
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=product, debug=False, strip=False, upx=False, console=False,
          icon=icon if sys.platform == "win32" else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=product)
if sys.platform == "darwin":
    app = BUNDLE(coll, name=f"{product}.app", bundle_identifier=packaging["bundle_id"], icon=icon,
                 version=info["version"].partition("-")[0], info_plist={"NSHighResolutionCapable": True})
