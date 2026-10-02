param(
    [switch]$BuildOnly,
    [switch]$SkipBuild,
    [string]$Version = "0.1.0"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Create the project's Python 3.10 environment first; expected $python"
}

Push-Location $projectRoot
try {
    if (-not $SkipBuild) {
        & $python -m pip install -r "packaging\build-requirements.txt"
        if ($LASTEXITCODE -ne 0) { throw "Could not install the pinned packaging tools." }

        & $python "packaging\create_icon.py"
        if ($LASTEXITCODE -ne 0) { throw "Could not render the Dogen application icon." }

        & $python -m PyInstaller --clean --noconfirm `
            --distpath "build\dist" --workpath "build\work" "packaging\dogen.spec"
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller could not create the Dogen application folder." }
    }

    & $python "scripts\verify_bundle.py" "build\dist\Dogen"
    if ($LASTEXITCODE -ne 0) {
        throw "The Dogen app bundle is missing required Coqui runtime files."
    }

    $buildRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot "build"))
    $ttsSmokeName = "tts-runtime-smoke-" + [guid]::NewGuid().ToString("N")
    $ttsSmokeRoot = [System.IO.Path]::GetFullPath((Join-Path $buildRoot $ttsSmokeName))
    $buildPrefix = $buildRoot.TrimEnd([char]'\') + [System.IO.Path]::DirectorySeparatorChar
    if (-not $ttsSmokeRoot.StartsWith($buildPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "The TTS smoke-test data must stay inside the project build directory."
    }
    $previousTtsHome = $env:TTS_HOME
    $previousSmokeCache = $env:DOGEN_TTS_SMOKE_CACHE
    $previousNumbaCacheLocatorClasses = $env:NUMBA_CACHE_LOCATOR_CLASSES
    try {
        New-Item -ItemType Directory -Path $ttsSmokeRoot | Out-Null
        $env:TTS_HOME = Join-Path $ttsSmokeRoot "tts"
        $env:DOGEN_TTS_SMOKE_CACHE = Join-Path $ttsSmokeRoot "numba-cache"
        $env:NUMBA_CACHE_LOCATOR_CLASSES = "UserWideCacheLocator"
        $ttsSmokeExecutable = Join-Path $projectRoot "build\dist\Dogen\Dogen.exe"
        $ttsSmokeProcess = Start-Process -FilePath $ttsSmokeExecutable `
            -ArgumentList "--verify-tts-runtime" `
            -WorkingDirectory $projectRoot -WindowStyle Hidden -Wait -PassThru
        if ($ttsSmokeProcess.ExitCode -ne 0) {
            throw "The frozen Coqui/inflect voice-import smoke test failed with exit code $($ttsSmokeProcess.ExitCode)."
        }
    }
    finally {
        if ($null -eq $previousTtsHome) {
            Remove-Item Env:TTS_HOME -ErrorAction SilentlyContinue
        }
        else {
            $env:TTS_HOME = $previousTtsHome
        }
        if ($null -eq $previousSmokeCache) {
            Remove-Item Env:DOGEN_TTS_SMOKE_CACHE -ErrorAction SilentlyContinue
        }
        else {
            $env:DOGEN_TTS_SMOKE_CACHE = $previousSmokeCache
        }
        if ($null -eq $previousNumbaCacheLocatorClasses) {
            Remove-Item Env:NUMBA_CACHE_LOCATOR_CLASSES -ErrorAction SilentlyContinue
        }
        else {
            $env:NUMBA_CACHE_LOCATOR_CLASSES = $previousNumbaCacheLocatorClasses
        }
        if (Test-Path -LiteralPath $ttsSmokeRoot) {
            $resolvedSmokeRoot = (Resolve-Path -LiteralPath $ttsSmokeRoot).Path
            if (-not $resolvedSmokeRoot.StartsWith($buildPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Refusing to remove TTS smoke-test data outside the project build directory."
            }
            Remove-Item -LiteralPath $resolvedSmokeRoot -Recurse -Force
        }
    }

    $smokeRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot "build\ko-speech-smoke"))
    if (-not $smokeRoot.StartsWith($buildPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "The Coqui smoke-test output must stay inside the project build directory."
    }
    if (Test-Path -LiteralPath $smokeRoot) {
        Remove-Item -LiteralPath $smokeRoot -Recurse -Force
    }
    try {
        & $python -m PyInstaller --noconfirm --onedir `
            --distpath (Join-Path $smokeRoot "dist") `
            --workpath (Join-Path $smokeRoot "work") `
            --specpath $smokeRoot `
            --collect-all ko_speech_tools `
            --name DogenKoSpeechSmoke "scripts\verify_ko_speech_runtime.py"
        if ($LASTEXITCODE -ne 0) { throw "Could not build the Coqui runtime smoke test." }

        $smokeExecutable = Join-Path $smokeRoot "dist\DogenKoSpeechSmoke\DogenKoSpeechSmoke.exe"
        & $smokeExecutable
        if ($LASTEXITCODE -ne 0) { throw "The frozen Coqui resource smoke test failed." }
    }
    finally {
        if (Test-Path -LiteralPath $smokeRoot) {
            Remove-Item -LiteralPath $smokeRoot -Recurse -Force
        }
    }

    $compiler = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    $compilerPath = if ($compiler) { $compiler.Source } else { $null }
    if (-not $compilerPath) {
        $candidatePaths = @(
            (Join-Path $projectRoot "build\tools\InnoSetup7\ISCC.exe"),
            (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 7\ISCC.exe"),
            (Join-Path $env:ProgramFiles "Inno Setup 7\ISCC.exe"),
            (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
            (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
        )
        foreach ($candidatePath in $candidatePaths) {
            if ($candidatePath -and (Test-Path -LiteralPath $candidatePath)) {
                $compilerPath = $candidatePath
                break
            }
        }
    }

    if (-not $compilerPath) {
        Write-Host "The Dogen application bundle is ready at build\dist\Dogen."
        if ($BuildOnly) { return }
        throw "Install Inno Setup 7 (or 6) to compile packaging\Dogen.iss into Dogen-Setup.exe."
    }
    if ($BuildOnly) { return }

    & $compilerPath "/DAppVersion=$Version" "packaging\Dogen.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup could not compile Dogen-Setup.exe." }
    Write-Host "Installer created at build\installer\Dogen-Setup.exe"
}
finally {
    Pop-Location
}
