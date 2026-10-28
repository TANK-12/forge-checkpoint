; Forge's Windows setup program (Inno Setup 6). release/build.py compiles it
; under Wine after it has made the windows-x64 folder, passing:
;   /DAppVersion=0.2.0  /DNumericVersion=0.2.0  /DBundle=<the Forge folder>
;   /DOutputDir=<--out>  /DOutputName=Forge-Setup-0.2.0
; It installs for this user only (no administrator prompt) into
; %LOCALAPPDATA%\Programs\Forge, adds Forge to the Start menu (a desktop icon
; is a tick box), and offers to start Forge at the end. The uninstaller takes
; the program out and keeps the user's things (%APPDATA%\Forge and
; %LOCALAPPDATA%\Forge) unless they say yes to removing those as well; even
; then it removes only Forge's own items there, never a folder that holds a
; data place they chose, and nothing else in those folders.
; Needs Inno Setup 6.3 or newer (x64compatible).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef NumericVersion
  #define NumericVersion AppVersion
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
VersionInfoVersion={#NumericVersion}
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
; forge_portable.py holds this mutex while Forge runs (Windows): setup and
; the uninstaller then ask the user to close Forge first.
AppMutex=local.forge.Forge
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
WizardSelectTasks=One more choice
SelectTasksDesc=Forge goes in your Start menu either way.
SelectTasksLabel2=Tick the box if you also want a Forge icon on the desktop, then click Install.
FinishedHeadingLabel=Forge is installed
FinishedLabel=Forge is in your Start menu. To remove it later, open the Start menu, type Add or remove programs, find Forge and choose Uninstall; your things stay unless you say otherwise.
FinishedLabelNoIcons=Forge is installed. To remove it later, open the Start menu, type Add or remove programs, find Forge and choose Uninstall.
SetupAppRunningError=Forge is open. Close its window, then click OK.%n%nClick Cancel to stop without installing.
UninstallAppRunningError=Forge is open. Close its window, then click OK.%n%nClick Cancel to leave Forge installed.
ConfirmUninstall=Remove Forge from this computer?%n%nYour settings and saves are kept unless you choose to remove them as well in a moment.
UninstalledAll=Forge has been removed from this computer.

[Tasks]
Name: "desktopicon"; Description: "Put a Forge icon on the desktop"; Flags: unchecked

[InstallDelete]
; A newer version replaces the old program files (never the user's things,
; which are elsewhere), so an app the new version dropped does not linger.
; release/build.py stops when the bundle has a folder that this list (or
; the uninstall list below) does not name.
Type: filesandordirs; Name: "{app}\apps"; Check: IsForgeFolder
Type: filesandordirs; Name: "{app}\assets"; Check: IsForgeFolder
Type: filesandordirs; Name: "{app}\groups"; Check: IsForgeFolder
Type: filesandordirs; Name: "{app}\hub"; Check: IsForgeFolder
Type: filesandordirs; Name: "{app}\release"; Check: IsForgeFolder
Type: filesandordirs; Name: "{app}\runtime"; Check: IsForgeFolder
Type: filesandordirs; Name: "{app}\sections"; Check: IsForgeFolder
Type: filesandordirs; Name: "{app}\shared"; Check: IsForgeFolder

[Files]
Source: "{#Bundle}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "forge.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; The bundled pythonw.exe (no console) with -B, as Forge.cmd starts it;
; forge_portable.py turns bytecode files off for the apps it starts and
; takes the same AppUserModelID, so a pywebview window shows Forge's icon
; and pins this shortcut rather than a bare pythonw.exe. Edge's app-mode
; window, the usual one, is Edge's own: README.txt says to pin Forge from
; the Start menu.
Name: "{autoprograms}\Forge"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "-B ""{app}\forge_portable.py"""; WorkingDir: "{app}"; IconFilename: "{app}\forge.ico"; Comment: "Forge: many small apps in one window"; AppUserModelID: "local.forge.Forge"
Name: "{autodesktop}\Forge"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "-B ""{app}\forge_portable.py"""; WorkingDir: "{app}"; IconFilename: "{app}\forge.ico"; Comment: "Forge: many small apps in one window"; AppUserModelID: "local.forge.Forge"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: "-B ""{app}\forge_portable.py"""; WorkingDir: "{app}"; Description: "Start Forge now"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; The program's own folders with anything written into them at run time,
; then the folder when it is empty. The user's things are never in here
; (Forge refuses a data place inside the program folder).
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\apps"
Type: filesandordirs; Name: "{app}\assets"
Type: filesandordirs; Name: "{app}\groups"
Type: filesandordirs; Name: "{app}\hub"
Type: filesandordirs; Name: "{app}\release"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\sections"
Type: filesandordirs; Name: "{app}\shared"
Type: dirifempty; Name: "{app}"

[Code]
procedure CurPageChanged(CurPageID: Integer);
begin
  { the Ready page is skipped, so the tick box page's button installs }
  if CurPageID = wpSelectTasks then
    WizardForm.NextButton.Caption := SetupMessage(msgButtonInstall);
end;

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
  // AppMutex covers Forge's own launcher; this also finds an app Forge
  // started that still runs from the program folder. PowerShell answers 7
  // when the Python bundled in this Forge folder is running (only runtime\:
  // the uninstaller's own first phase runs from the program folder and
  // waits for this one); any other answer, a PowerShell error included,
  // counts as not running. Without PowerShell (or under Wine) the check
  // says no and the uninstaller goes on; a file still in use is then left
  // and named by Windows. A brace comment cannot hold the folder's
  // constant: its closing brace would end the comment.
  Folder := ExpandConstant('{app}\runtime');
  // PowerShell reads each of these as a single quote: double every one.
  StringChangeEx(Folder, #$0027, #$0027#$0027, True);
  StringChangeEx(Folder, #$2018, #$2018#$2018, True);
  StringChangeEx(Folder, #$2019, #$2019#$2019, True);
  StringChangeEx(Folder, #$201A, #$201A#$201A, True);
  StringChangeEx(Folder, #$201B, #$201B#$201B, True);
  // StartsWith, not -like: a [ or ] in the folder is no wildcard.
  Script := '$p = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and ' +
    '$_.Path.StartsWith(''' + Folder + '\'', [StringComparison]::OrdinalIgnoreCase) }; ' +
    'if ($p) { exit 7 } else { exit 0 }';
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -Command "' + Script + '"', '', SW_HIDE,
    ewWaitUntilTerminated, Code) and (Code = 7);
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
    if MsgBox('Forge is open. Close its window, then click OK.' + #13#10#13#10 +
      'Click Cancel to leave Forge installed.', mbInformation, MB_OKCANCEL) = IDCANCEL then
    begin
      Result := False;
      exit;
    end;
  end;
end;

const
  PlaceMarker = 'forge-data.json';  { the file at the top of every Forge data place }
  ReparsePoint = $400;  { FILE_ATTRIBUTE_REPARSE_POINT: a link, never followed }

function HoldsPlace(Folder: String): Boolean;
var
  Found: TFindRec;
begin
  // True when a Forge data place (its marker file) is in this folder or
  // anywhere under it: the uninstaller never removes such a folder.
  Result := FileExists(Folder + '\' + PlaceMarker);
  if Result then
    exit;
  if not FindFirst(Folder + '\*', Found) then
    exit;
  try
    repeat
      if (Found.Name <> '.') and (Found.Name <> '..') and
        ((Found.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) and
        ((Found.Attributes and ReparsePoint) = 0) then
        if HoldsPlace(Folder + '\' + Found.Name) then
        begin
          Result := True;
          break;
        end;
    until not FindNext(Found);
  finally
    FindClose(Found);
  end;
end;

function LocalItems(Folder: String): TArrayOfString;
var
  Found: TFindRec;
  Count: Integer;
  Keep: Boolean;
begin
  // What Forge keeps in %LOCALAPPDATA%\Forge (cache, logs, window and app
  // state): everything there except links and folders that hold a place.
  Count := 0;
  SetArrayLength(Result, 0);
  if not FindFirst(Folder + '\*', Found) then
    exit;
  try
    repeat
      Keep := (Found.Name = '.') or (Found.Name = '..') or
        ((Found.Attributes and ReparsePoint) <> 0);
      if not Keep and ((Found.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) then
        Keep := HoldsPlace(Folder + '\' + Found.Name);
      if not Keep then
      begin
        SetArrayLength(Result, Count + 1);
        Result[Count] := Folder + '\' + Found.Name;
        Count := Count + 1;
      end;
    until not FindNext(Found);
  finally
    FindClose(Found);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Roaming, Local, Pointer, Place, Folders: String;
  Items: TArrayOfString;
  I: Integer;
begin
  if (CurUninstallStep <> usPostUninstall) or UninstallSilent then
    exit;
  // Only Forge's own items are offered: the pointer file and the default
  // data place in %APPDATA%\Forge (anything else there, such as an older
  // Forge's files, stays), and the cache, logs and state in
  // %LOCALAPPDATA%\Forge. A folder that holds a data place the user chose
  // is never among them.
  Roaming := ExpandConstant('{userappdata}\Forge');
  Local := ExpandConstant('{localappdata}\Forge');
  Pointer := Roaming + '\where.json';
  Place := Roaming + '\Forge data';
  Items := LocalItems(Local);
  Folders := '';
  // Windows wraps the sentences; a line break here only starts a new line.
  if FileExists(Place + '\' + PlaceMarker) then
    Folders := Folders + 'Your settings, saves and app data:' + #13#10 + Place + #13#10#13#10;
  if FileExists(Pointer) then
    Folders := Folders + 'The note of where your things are kept:' + #13#10 + Pointer + #13#10#13#10;
  if GetArrayLength(Items) > 0 then
    Folders := Folders + 'Cache, logs and window data (game scores, view choices):' + #13#10 +
      Local + #13#10#13#10;
  if Folders = '' then
    exit;
  if MsgBox('Forge has been removed. Your things are still kept, so a new install of ' +
    'Forge picks them up again.' + #13#10#13#10 + Folders +
    'Remove these too? They are deleted for good, not moved to the Recycle Bin. ' +
    'Nothing else is touched, including a data folder you picked yourself.',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
  begin
    if FileExists(Place + '\' + PlaceMarker) then
      DelTree(Place, True, True, True);
    DeleteFile(Pointer);
    for I := 0 to GetArrayLength(Items) - 1 do
      if DirExists(Items[I]) then
        DelTree(Items[I], True, True, True)
      else
        DeleteFile(Items[I]);
    RemoveDir(Roaming);
    RemoveDir(Local);
  end;
end;
