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

    $smokeRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot "build\ko-speech-smoke"))
    $buildRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot "build"))
    $buildPrefix = $buildRoot.TrimEnd([char]'\') + [System.IO.Path]::DirectorySeparatorChar
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
