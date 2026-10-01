"""PyInstaller one-folder bundle; Inno Setup wraps it in Dogen-Setup.exe."""
import importlib.util
import os
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    copy_metadata,
)


PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
datas = [(os.path.join(PROJECT_ROOT, "ui", "styles.qss"), "ui")]
binaries = []
hiddenimports = []

# These libraries load plugins, language assets, or model helpers dynamically.
# Coqui's Korean phonemizer also needs ko_speech_tools' namespace-package data.
for package in ("whisper", "ollama", "noisereduce", "ko_speech_tools"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports

# Coqui TTS cannot be imported by PyInstaller's isolated submodule scanner with
# some supported Transformers versions. Enumerate its Python files without
# importing the package, while retaining its non-code model/config resources.
tts_spec = importlib.util.find_spec("TTS")
if not tts_spec or not tts_spec.submodule_search_locations:
    raise RuntimeError("coqui-tts is missing from the build environment")
tts_root = Path(next(iter(tts_spec.submodule_search_locations)))
for module_file in tts_root.rglob("*.py"):
    relative = module_file.relative_to(tts_root)
    if any(
        part.lower() in {"test", "tests", "testing", "examples", "bin", "notebooks"}
        for part in relative.parts
    ):
        continue
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts.pop()
    else:
        parts[-1] = module_file.stem
    if parts:
        hiddenimports.append("TTS." + ".".join(parts))
datas += collect_data_files("TTS")
binaries += collect_dynamic_libs("TTS")
datas += copy_metadata("coqui-tts")

a = Analysis(
    [os.path.join(PROJECT_ROOT, "main.py")],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(PROJECT_ROOT, "packaging", "runtime_hook.py")],
    excludes=["pytest", "IPython", "notebook", "jupyter"],
    noarchive=False,
    # Coqui scans this package with os.listdir(__file__'s directory) at import.
    module_collection_mode={
        "TTS.vocoder.configs": "pyz+py",
        "TTS.vocoder.layers.wavegrad": "pyz+py",
    },
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Dogen",
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
    icon=os.path.join(PROJECT_ROOT, "build", "artifacts", "dogen.ico"),
    version=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Dogen",
)
