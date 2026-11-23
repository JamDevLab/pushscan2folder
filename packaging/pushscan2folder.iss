; Inno Setup script for the Windows installer of pushscan2folder.
; Built by .github/workflows/release.yml after PyInstaller made the folder
; dist\pushscan2folder:
;   ISCC /DAppVersion=0.4.0 packaging\pushscan2folder.iss
; Installs for the current user only (no administrator rights), into
; %LOCALAPPDATA%\Programs\pushscan2folder, with Start menu entries and an
; entry under Settings > Apps for uninstalling.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define Exe "pushscan2folder.exe"

[Setup]
; Never change the AppId: Windows uses it to find an installed version.
AppId={{6B3E2F4A-8C1D-4E5F-9A7B-2D4C6E8F0A13}
AppName=pushscan2folder
AppVersion={#AppVersion}
AppVerName=pushscan2folder {#AppVersion}
AppPublisher=JamDevLab
AppPublisherURL=https://github.com/JamDevLab/pushscan2folder
AppSupportURL=https://github.com/JamDevLab/pushscan2folder/issues
DefaultDirName={autopf}\pushscan2folder
DefaultGroupName=pushscan2folder
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=pushscan2folder-{#AppVersion}-windows-setup
SetupIconFile=pushscan2folder.ico
UninstallDisplayIcon={app}\{#Exe}
UninstallDisplayName=pushscan2folder
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; The background instance is stopped by the code below, not by Restart Manager.
CloseApplications=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[CustomMessages]
en.RunSetup=Set up and start pushscan2folder
de.RunSetup=pushscan2folder einrichten und starten
en.DeleteSettings=Also delete the settings and the log of pushscan2folder?%n%nYour scans are not touched.
en.StoppingInstance=Stopping pushscan2folder (a running scan is finished first, this can take a few minutes)...
de.StoppingInstance=pushscan2folder wird beendet (ein laufender Scan wird zuerst abgeschlossen, das kann einige Minuten dauern)...
de.DeleteSettings=Auch die Einstellungen und das Protokoll von pushscan2folder löschen?%n%nDeine Scans bleiben erhalten.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; An update must not mix old and new libraries.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\pushscan2folder\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\pushscan2folder"; Filename: "{app}\{#Exe}"
Name: "{autodesktop}\pushscan2folder"; Filename: "{app}\{#Exe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#Exe}"; Description: "{cm:RunSetup}"; Flags: postinstall nowait skipifsilent

[Code]
var
  WasRunning: Boolean;
  StopPage: TOutputProgressWizardPage;

{ Shown while an update waits for the background instance to stop. }
procedure InitializeWizard;
begin
  StopPage := CreateOutputProgressPage(SetupMessage(msgWizardPreparing),
                                       CustomMessage('StoppingInstance'));
end;

{ Run the installed program without a window and without waiting for Enter. }
function RunHidden(const Args: String): Integer;
var
  Code: Integer;
begin
  Result := -1;
  if Exec(ExpandConstant('{app}\{#Exe}'), '--no-pause ' + Args, '', SW_HIDE,
          ewWaitUntilTerminated, Code) then
    Result := Code;
end;

{ An update: stop the background instance so its files can be replaced. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  WasRunning := False;
  if FileExists(ExpandConstant('{app}\{#Exe}')) then
  begin
    WasRunning := RunHidden('status') = 0;
    if WasRunning then
    begin
      { `stop` waits for a running scan (up to 10 minutes) and has no timeout
        option, and the installer window stays idle meanwhile: say why. }
      StopPage.Show;
      try
        RunHidden('stop');
      finally
        StopPage.Hide;
      end;
    end;
  end;
end;

{ ... and start it again afterwards. Known limit: the background info file
  keeps only the PID and the log file, not the options of the old instance, so
  the restart uses the defaults (config file in %APPDATA%, default log file). }
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WasRunning then
    RunHidden('start');
end;

{ Uninstall: stop, remove the autostart entry and, if wanted, the settings. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Args: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    Args := 'uninstall --yes';
    if SuppressibleMsgBox(CustomMessage('DeleteSettings'), mbConfirmation,
                          MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
      Args := Args + ' --purge';
    RunHidden(Args);
  end;
end;
