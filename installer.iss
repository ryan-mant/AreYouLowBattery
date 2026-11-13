[Setup]
AppId={{8E9A74B2-4C12-4F90-9A1D-2B7E5C8D3F01}
AppName=AreYouLowBattery
AppVersion=0.5.3.1
AppPublisher=AreYouLowBattery Open Source Project
AppPublisherURL=https://github.com/ryan-mant/AreYouLowBattery
AppSupportURL=https://github.com/ryan-mant/AreYouLowBattery/issues
DefaultDirName={autopf}\AreYouLowBattery
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=AreYouLowBattery-Windows-Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\areyoulowbattery.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "autostart"; Description: "Start AreYouLowBattery automatically with Windows"; GroupDescription: "Additional tasks:"; Flags: unchecked
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Additional tasks:"; Flags: unchecked

[Files]
Source: "dist\areyoulowbattery\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{userstartup}\AreYouLowBattery.bat"

[Icons]
Name: "{autoprograms}\AreYouLowBattery"; Filename: "{app}\areyoulowbattery.exe"; Parameters: "--tray --show"
Name: "{autodesktop}\AreYouLowBattery"; Filename: "{app}\areyoulowbattery.exe"; Parameters: "--tray --show"; Tasks: desktopicon
Name: "{userstartup}\AreYouLowBattery"; Filename: "{app}\areyoulowbattery.exe"; Parameters: "--tray"; Tasks: autostart

[Run]
Filename: "{app}\areyoulowbattery.exe"; Parameters: "--tray --show"; Description: "Launch AreYouLowBattery now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{userstartup}\AreYouLowBattery.bat"
Type: files; Name: "{userstartup}\AreYouLowBattery.lnk"
