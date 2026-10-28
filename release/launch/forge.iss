; Forge's Windows setup program (Inno Setup 6). release/build.py compiles it
; under Wine after it has made the windows-x64 folder, passing:
;   /DAppVersion=0.2.0  /DBundle=<the Forge folder>  /DOutputDir=<--out>
;   /DOutputName=Forge-Setup-0.2.0
; It installs for this user only (no administrator prompt) into
; %LOCALAPPDATA%\Programs\Forge, adds Forge to the Start menu (a desktop icon
; is a tick box), and offers to start Forge at the end. The uninstaller takes
; the program out and keeps the user's things (%APPDATA%\Forge and
; %LOCALAPPDATA%\Forge) unless they say yes to removing those as well; a data
; folder they moved somewhere else is never touched.
; Needs Inno Setup 6.3 or newer (x64compatible).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef Bundle
  #define Bundle "..\..\build\windows-x64\Forge"
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif
#ifndef OutputName
  #define OutputName "Forge-Setup-" + AppVersion
#endif

[Setup]
AppId=local.forge.Forge
AppName=Forge
AppVersion={#AppVersion}
AppVerName=Forge {#AppVersion}
AppPublisher=Forge
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Forge setup
DefaultDirName={autopf}\Forge
DefaultGroupName=Forge
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableWelcomePage=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
UsePreviousAppDir=yes
CloseApplications=yes
RestartApplications=no
WizardStyle=modern
WizardSizePercent=100
SetupIconFile=forge.ico
WizardImageFile=wizard-202.bmp,wizard-404.bmp
WizardSmallImageFile=wizard-small-58.bmp,wizard-small-116.bmp
UninstallDisplayIcon={app}\forge.ico
UninstallDisplayName=Forge
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
Compression=lzma2
SolidCompression=yes

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel1=Forge {#AppVersion}
WelcomeLabel2=Forge is one window for many small apps that run on this computer: games, creative tools, readers and research helpers.%n%nThis puts Forge in your Start menu. It needs no administrator rights and takes about a minute.%n%nYour settings and saves are kept apart from the program, so installing a newer Forge later keeps them.
FinishedHeadingLabel=Forge is installed
FinishedLabel=Forge is in your Start menu. To remove it later, open Settings, Apps, Installed apps, find Forge and choose Uninstall; your things stay unless you say otherwise.
FinishedLabelNoIcons=Forge is installed. To remove it later, open Settings, Apps, Installed apps, find Forge and choose Uninstall.

[Tasks]
Name: "desktopicon"; Description: "Put a Forge icon on the desktop"; Flags: unchecked

[InstallDelete]
; A newer version replaces the old program files (never the user's things,
; which are elsewhere), so an app the new version dropped does not linger.
Type: filesandordirs; Name: "{app}\apps"; Check: IsForgeFolder
Type: filesandordirs; Name: "{app}\shared"; Check: IsForgeFolder
Type: filesandordirs; Name: "{app}\hub"; Check: IsForgeFolder
Type: filesandordirs; Name: "{app}\runtime"; Check: IsForgeFolder
Type: filesandordirs; Name: "{app}\sections"; Check: IsForgeFolder
Type: filesandordirs; Name: "{app}\groups"; Check: IsForgeFolder

[Files]
Source: "{#Bundle}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "forge.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Forge.cmd sets PYTHONDONTWRITEBYTECODE and starts Forge without a console;
; run minimised so its own console never shows.
Name: "{autoprograms}\Forge"; Filename: "{app}\Forge.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\forge.ico"; Comment: "Forge: many small apps in one window"; Flags: runminimized
Name: "{autodesktop}\Forge"; Filename: "{app}\Forge.cmd"; WorkingDir: "{app}"; IconFilename: "{app}\forge.ico"; Comment: "Forge: many small apps in one window"; Flags: runminimized; Tasks: desktopicon

[Run]
Filename: "{app}\Forge.cmd"; WorkingDir: "{app}"; Description: "Start Forge now"; Flags: postinstall nowait skipifsilent runminimized

[UninstallDelete]
; Only what Forge itself may have left in the program folder, then the
; folder when it is empty. The user's things are not in here.
Type: filesandordirs; Name: "{app}\__pycache__"
Type: dirifempty; Name: "{app}"

[Code]
function IsForgeFolder(): Boolean;
begin
  { only a folder that already holds Forge is cleared before the copy }
  Result := FileExists(ExpandConstant('{app}\forge_portable.py'));
end;

function ForgeRunning(): Boolean;
var
  Code: Integer;
  Folder, Script: String;
begin
  { PowerShell answers 1 when the Python bundled in this Forge folder is
    running (only runtime\: the uninstaller's own first phase runs from
    {app} and waits for this one). Without PowerShell (or under Wine) the
    check says no and the uninstaller goes on; a file still in use is then
    left and named by Windows. }
  Folder := ExpandConstant('{app}\runtime');
  StringChangeEx(Folder, '''', '''''', True);  { a ' in a path, as PowerShell writes it }
  Script := '$p = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -like ''' +
    Folder + '\*'' }; if ($p) { exit 1 } else { exit 0 }';
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -Command "' + Script + '"', '', SW_HIDE,
    ewWaitUntilTerminated, Code) and (Code = 1);
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  while ForgeRunning() do
  begin
    if UninstallSilent then
    begin
      Result := False;
      exit;
    end;
    if MsgBox('Forge is still open. Close its window, then press OK.' + #13#10 +
      'Press Cancel to leave Forge installed.', mbInformation, MB_OKCANCEL) = IDCANCEL then
    begin
      Result := False;
      exit;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Roaming, Local, Folders: String;
begin
  if (CurUninstallStep <> usPostUninstall) or UninstallSilent then
    exit;
  Roaming := ExpandConstant('{userappdata}\Forge');
  Local := ExpandConstant('{localappdata}\Forge');
  Folders := '';
  if DirExists(Roaming) then
    Folders := Folders + '    ' + Roaming + '   (settings, saves, app data)' + #13#10;
  if DirExists(Local) then
    Folders := Folders + '    ' + Local + '   (cache and logs)' + #13#10;
  if Folders = '' then
    exit;
  if MsgBox('Forge has been removed. Your things are still kept here, so a new' + #13#10 +
    'install of Forge picks them up again:' + #13#10#13#10 + Folders + #13#10 +
    'Remove these folders too? They are deleted for good, not moved to the' + #13#10 +
    'Recycle Bin. A data folder you moved to another place is not touched.',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
  begin
    DelTree(Roaming, True, True, True);
    DelTree(Local, True, True, True);
  end;
end;
