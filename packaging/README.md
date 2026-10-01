# Windows installer

`Dogen-Setup.exe` installs the application without requiring Python or a `.bat`
file. The first launch opens a setup guide that checks the local speech models and
Ollama, can download the speech models, lists installed conversation models, and
lets the tester request an Ollama model download after a size warning. Selecting a
model in this guide saves the preference only; Dogen still asks the user to load it
from **File → Model**, so setup never loads a model into VRAM automatically. The same
guide remains available later from **File → Setup guide…**.

Ollama and its conversation-model weights remain separate installs. Speech-model
weights can be downloaded during setup and live under `%LOCALAPPDATA%\Dogen\models`. Settings,
conversations, and local diagnostics live under `%LOCALAPPDATA%\Dogen`; uninstalling
the app leaves that user data intact.

## Build on Windows

Use 64-bit Python 3.10 and install Inno Setup 7 (Inno Setup 6 also works). From the project root, run:

```powershell
.\packaging\build_windows.ps1
```

The script installs the pinned PyInstaller build tool, renders the Dogen face as a
Windows icon, builds a one-folder application, then compiles the user-level Inno
Setup installer. The application bundle is at `build\dist\Dogen`; the installer is
at `build\installer\Dogen-Setup.exe`. `-BuildOnly` builds the application folder
without compiling the installer.

The first build is large because the local Whisper and Coqui pipelines include
PyTorch. No personal settings, database, logs, audio, or downloaded model weights
are included in the build.
