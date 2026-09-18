@echo off
setlocal

set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "PREFLIGHT=%ROOT%scripts\preflight.py"
set "SETUP_MARKER=%VENV%\.dogen_setup_ok"
set "WHISPER_MODEL=small.en"
set "TTS_MODEL=tts_models/en/ljspeech/tacotron2-DDC"
:: Para voz masculina (requer eSpeak-NG instalado): tts_models/en/sam/tacotron-DDC
set "OLLAMA_MODEL=mistral"

:: Passe "reinstall" como argumento para forcar a checagem completa de pacotes de novo
:: (ex: start.bat reinstall) apos mudar requirements.txt ou suspeitar de ambiente corrompido.
if /i "%~1"=="reinstall" (
    del /f /q "%SETUP_MARKER%" >nul 2>&1
    echo Forcando reinstalacao completa de dependencias...
)

if exist "%SETUP_MARKER%" goto :after_setup

:: ── 0. Pre-requisitos de sistema ────────────────────────────────────────────
echo [0/5] Verificando pre-requisitos de sistema...

:: Visual C++ Redistributable (exigido pelo PyTorch)
winget install --id Microsoft.VCRedist.2015+.x64 --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
if errorlevel 1 (
    echo    VC++ Redist: verifique se ja esta instalado ou baixe em https://aka.ms/vs/17/release/vc_redist.x64.exe
) else (
    echo    Visual C++ Redistributable ok.
)

:: eSpeak-NG (phonemizer exigido pelo modelo TTS masculino)
where espeak-ng >nul 2>&1
if errorlevel 1 (
    echo    Instalando eSpeak-NG...
    winget install --id eSpeak.eSpeakNG --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
    :: Adiciona ao PATH da sessao atual caso o winget nao tenha atualizado ainda
    if exist "C:\Program Files\eSpeak NG\espeak-ng.exe" (
        set "PATH=%PATH%;C:\Program Files\eSpeak NG"
        echo    eSpeak-NG instalado.
    ) else (
        echo    AVISO: eSpeak-NG nao encontrado automaticamente.
        echo    Instale manualmente em https://espeak-ng.org/ e reinicie o bat.
    )
) else (
    echo    eSpeak-NG ok.
)

:: ── 1. Ambiente virtual ────────────────────────────────────────────────────
echo [1/5] Verificando ambiente virtual...
if not exist "%PYTHON%" (
    echo Criando ambiente virtual em .venv...
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo.
        echo ERRO: 'python' nao encontrado no PATH.
        echo Instale Python 3.10 em https://www.python.org/downloads/
        echo.
        pause & exit /b 1
    )
)

:: ── 2. Dependencias ────────────────────────────────────────────────────────
echo [2/5] Instalando dependencias...
"%PYTHON%" -m pip install --quiet --upgrade pip wheel setuptools

:: Instala todas as dependencias (coqui-tts pode puxar versao CUDA do torch aqui)
"%PYTHON%" -m pip install --quiet --prefer-binary -r "%ROOT%requirements.txt"
if errorlevel 1 (
    echo.
    echo ERRO: falha ao instalar dependencias.
    echo.
    echo Causas comuns:
    echo   - Extensao C sem compilador:
    echo     winget install Microsoft.VisualStudio.2022.BuildTools --override "--passive --add Microsoft.VisualStudio.Workload.VCTools"
    echo   - Sem internet. Conflito de versoes: delete .venv e tente de novo.
    echo.
    pause & exit /b 1
)

:: Garante torch+torchaudio CPU por ultimo (torch<2.9 evita dependencia de torchcodec/CUDA)
echo    Fixando torch+torchaudio CPU (versoes pareadas)...
"%PYTHON%" -m pip install --quiet --force-reinstall "torch<2.9" "torchaudio<2.9" --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 (
    echo ERRO: falha ao instalar PyTorch. Verifique sua conexao com a internet.
    pause & exit /b 1
)
:: Verifica se carrega apos instalacao
"%PYTHON%" -c "import torch, torchaudio; torch.zeros(1)" >nul 2>&1
if errorlevel 1 (
    echo ERRO: PyTorch instalado mas nao carrega ^(DLL faltando^).
    echo Instale o Visual C++ Redistributable: https://aka.ms/vs/17/release/vc_redist.x64.exe
    pause & exit /b 1
)
echo    PyTorch funcional. Para GPU, veja docs/SETUP.md.

:: Marca o ambiente Python como pronto: nas proximas execucoes os passos 0-2
:: (winget + pip, os mais lentos) sao pulados inteiramente. Rode "start.bat
:: reinstall" para refazer essa checagem depois de mudar requirements.txt.
echo ok > "%SETUP_MARKER%"

:after_setup
:: ── 3. Whisper ─────────────────────────────────────────────────────────────
echo [3/5] Verificando modelo Whisper (%WHISPER_MODEL%)...
"%PYTHON%" "%PREFLIGHT%" check-whisper "%WHISPER_MODEL%" 2>nul
if errorlevel 1 (
    echo    Baixando modelo Whisper %WHISPER_MODEL%...
    "%PYTHON%" "%PREFLIGHT%" download-whisper "%WHISPER_MODEL%"
    if errorlevel 1 (
        echo ERRO: falha ao baixar Whisper. Verifique sua conexao com a internet.
        pause & exit /b 1
    )
) else (
    echo    Whisper %WHISPER_MODEL% ja em cache.
)

:: ── 4. Coqui TTS ───────────────────────────────────────────────────────────
echo [4/5] Verificando modelo TTS (%TTS_MODEL%)...
"%PYTHON%" "%PREFLIGHT%" check-tts "%TTS_MODEL%" 2>nul
if errorlevel 1 (
    echo    Baixando modelo TTS %TTS_MODEL%...
    "%PYTHON%" "%PREFLIGHT%" download-tts "%TTS_MODEL%"
    if errorlevel 1 (
        echo.
        echo ERRO: falha ao baixar o modelo TTS.
        echo.
        echo Causas comuns:
        echo   - Sem internet para baixar o modelo.
        echo   - torch/torchcodec incompativeis: delete .venv e rode novamente.
        echo   - Se o erro mencionar 'espeak', instale: https://espeak-ng.org/
        echo.
        pause & exit /b 1
    )
) else (
    echo    TTS %TTS_MODEL% ja em cache.
)

:: ── 5. Ollama ──────────────────────────────────────────────────────────────
echo [5/5] Verificando Ollama (%OLLAMA_MODEL%)...
ollama list >nul 2>&1
if errorlevel 1 (
    echo    AVISO: Ollama nao encontrado no PATH.
    echo    Instale em https://ollama.com e inicie antes de usar o Dogen.
) else (
    ollama list 2>nul | findstr /i "%OLLAMA_MODEL%" >nul
    if errorlevel 1 (
        echo    Baixando modelo Ollama %OLLAMA_MODEL%...
        ollama pull %OLLAMA_MODEL%
    ) else (
        echo    Ollama %OLLAMA_MODEL% ja disponivel.
    )
)

:: ── Iniciar ────────────────────────────────────────────────────────────────
echo.
echo Iniciando Dogen...
cd /d "%ROOT%"
set "PYTHONWARNINGS=ignore::FutureWarning,ignore::DeprecationWarning"
"%PYTHON%" main.py
if errorlevel 1 (
    echo.
    echo Dogen encerrou com erro. Verifique app.log para detalhes.
    pause
)
