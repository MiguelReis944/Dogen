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

## Troubleshooting

- If speech recognition or the local voice cannot load, follow the status message. Use
  **File → Setup guide…** to prepare or repair speech models, then select **Retry loading**.
- If an older installer reports `could not get source code` while checking the English
  voice, install a build made from the current packaging files. Coqui and `typeguard`
  inspect Python source during setup; the current build preserves those files and runs
  the frozen voice-check path before creating the installer. This smoke test verifies
  imports and setup checks, not voice-model download, synthesis quality, or playback on
  every audio device.
- If microphone validation blocks launch before the main window appears, reconnect the
  microphone or correct Windows privacy/device settings, then restart Dogen. If recording
  fails after launch, follow the status message and select **Retry loading** after fixing it.
- If an individual recording or turn fails, Dogen keeps the error visible, returns to the
  recording state when possible, and allows another attempt without restarting.
- Ollama remains a separate local service. Start Ollama, install the desired conversation
  model there, then use **File → Model → Refresh model list** and **Load selected model**.

Hardware, Windows permissions, local model files, and Ollama availability vary between
computers; Dogen reports these environment failures instead of silently ignoring them.

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
