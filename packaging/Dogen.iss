#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6A301AF1-28A3-4BF7-872F-40B5D1771E4C}}
AppName=Dogen
AppVersion={#AppVersion}
AppPublisher=Dogen
DefaultDirName={localappdata}\Programs\Dogen
DefaultGroupName=Dogen
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\Dogen.exe
SetupIconFile=..\build\artifacts\dogen.ico
OutputDir=..\build\installer
OutputBaseFilename=Dogen-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\build\dist\Dogen\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Dogen"; Filename: "{app}\Dogen.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Dogen"; Filename: "{app}\Dogen.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{autoprograms}\Uninstall Dogen"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\Dogen.exe"; Description: "Launch Dogen"; Flags: nowait postinstall skipifsilent
