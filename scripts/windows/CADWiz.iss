; SPDX-License-Identifier: LGPL-2.1-or-later
#ifndef AppVersion
  #define AppVersion "0.9.0"
#endif
#ifndef SourceRoot
  #define SourceRoot "..\.."
#endif
#ifndef OutputPath
  #define OutputPath "..\..\..\..\outputs\CADWiz-0.9.0-Beta"
#endif
[Setup]
AppId=CADWiz
AppName=CADWiz
AppVersion={#AppVersion}
AppPublisher=WizLabs
AppPublisherURL=https://cadwiz.app
DefaultDirName={localappdata}\CADWiz
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
WizardSizePercent=110
DisableWelcomePage=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
Uninstallable=no
CreateAppDir=no
CloseApplications=no
RestartApplications=no
OutputDir={#OutputPath}
OutputBaseFilename=CADWiz-Setup-{#AppVersion}
SetupIconFile={#SourceRoot}\CADWiz\Resources\icons\cadwiz.ico
Compression=lzma2
SolidCompression=yes
SetupLogging=yes
SetupMutex=Local\CADWizSetup
VersionInfoVersion={#AppVersion}.0

[Messages]
WelcomeLabel1=CADWiz for FreeCAD
WelcomeLabel2=Create, mark and edit your models with your AI assistant.%n%nSetup finds FreeCAD, verifies its add-on folder and keeps recovery copies when upgrading.%n%nSave your work and close FreeCAD before continuing.
FinishedHeadingLabel=CADWiz is installed
FinishedLabel=Open FreeCAD to see the CADWiz panel.%n%nIn CADWiz, choose Setup and connect your assistant. The connection is confirmed when your assistant can inspect the open model.
ButtonInstall=Install CADWiz

[Files]
Source: "{#SourceRoot}\scripts\windows_installer.py"; DestDir: "{tmp}\payload\scripts"; Flags: dontcopy
Source: "{#SourceRoot}\scripts\windows_wizard.py"; DestDir: "{tmp}\payload\scripts"; Flags: dontcopy
Source: "{#SourceRoot}\scripts\windows_shortcuts.ps1"; DestDir: "{tmp}\payload\scripts"; Flags: dontcopy
Source: "{#SourceRoot}\scripts\uninstall_windows.ps1"; DestDir: "{tmp}\payload\scripts"; Flags: dontcopy
Source: "{#SourceRoot}\CADWiz\*"; DestDir: "{tmp}\payload\CADWiz"; Excludes: "__pycache__,*.pyc,*.pyo"; Flags: dontcopy recursesubdirs createallsubdirs

[Run]
Filename: "{code:GetFreeCADExe}"; Parameters: """{code:GetManager}"" --open"; WorkingDir: "{code:GetFreeCADDirectory}"; Description: "Open FreeCAD with CADWiz"; Flags: postinstall nowait skipifsilent runascurrentuser; Check: CanOpenFreeCAD

[Code]
var
  FreeCADPage: TInputFileWizardPage;
  DesktopChoice: TNewCheckBox;
  DataFolder, ResultFile, PythonExe, VerifiedFreeCAD: String;
  PayloadReady, Installed: Boolean;

function Quoted(const Value: String): String;
begin
  Result := '"' + Value + '"';
end;

function DataDir: String;
begin
  Result := ExpandConstant('{param:DATADIR|}');
  if Result = '' then Result := ExpandConstant('{localappdata}\CADWiz');
end;

procedure EnsurePayload;
begin
  if not PayloadReady then begin
    ExtractTemporaryFiles('{tmp}\payload\*');
    PayloadReady := True;
  end;
end;

function Candidate(const Root: String): String;
var FindRec: TFindRec;
begin
  Result := '';
  if FindFirst(Root + '\FreeCAD*', FindRec) then begin
    try
      repeat
        if FileExists(Root + '\' + FindRec.Name + '\bin\FreeCAD.exe') then
          Result := Root + '\' + FindRec.Name + '\bin\FreeCAD.exe';
      until not FindNext(FindRec);
    finally FindClose(FindRec); end;
  end;
end;

procedure InitializeWizard;
var Found: String;
begin
  PayloadReady := False; Installed := False;
  DataFolder := DataDir;
  ResultFile := ExpandConstant('{tmp}\setup-result.ini');
  FreeCADPage := CreateInputFilePage(wpWelcome, 'Ready to install CADWiz',
    'Check your FreeCAD installation',
    'Setup detected the FreeCAD application below. If it is missing or different, choose FreeCAD.exe. No folder commands or repository settings are needed.');
  FreeCADPage.Add('FreeCAD application:', 'FreeCAD|FreeCAD.exe', '.exe');
  DesktopChoice := TNewCheckBox.Create(WizardForm);
  DesktopChoice.Parent := FreeCADPage.Surface;
  DesktopChoice.Caption := 'Add a CADWiz desktop shortcut';
  DesktopChoice.Left := FreeCADPage.Edits[0].Left;
  DesktopChoice.Top := FreeCADPage.Edits[0].Top + FreeCADPage.Edits[0].Height + ScaleY(16);
  DesktopChoice.Width := FreeCADPage.SurfaceWidth;
  DesktopChoice.Height := ScaleY(24);
  DesktopChoice.Checked := ExpandConstant('{param:NODESKTOP|0}') <> '1';
  Found := ExpandConstant('{param:FREECADBIN|}');
  if Found <> '' then Found := AddBackslash(Found) + 'FreeCAD.exe';
  if Found = '' then Found := Candidate(ExpandConstant('{autopf}'));
  if Found = '' then Found := Candidate(ExpandConstant('{localappdata}\Programs'));
  FreeCADPage.Values[0] := Found;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = FreeCADPage.ID then WizardForm.NextButton.Caption := '&Install CADWiz'
  else if CurPageID = wpWelcome then WizardForm.NextButton.Caption := SetupMessage(msgButtonNext)
  else if CurPageID = wpFinished then WizardForm.NextButton.Caption := SetupMessage(msgButtonFinish);
end;

function RunHelper(const Action, Extra: String): Boolean;
var Code: Integer; Args: String;
begin
  DeleteFile(ResultFile);
  Args := Quoted(ExpandConstant('{tmp}\payload\scripts\windows_wizard.py')) + ' ' + Action +
    ' --data-dir ' + Quoted(DataFolder) + ' --ini ' + Quoted(ResultFile) + ' ' + Extra;
  Result := Exec(PythonExe, Args, ExpandConstant('{tmp}\payload\scripts'), SW_HIDE, ewWaitUntilTerminated, Code);
  Result := Result and (Code = 0) and (GetIniString('result', 'ok', '0', ResultFile) = '1');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = FreeCADPage.ID then begin
    VerifiedFreeCAD := FreeCADPage.Values[0];
    PythonExe := ExtractFilePath(VerifiedFreeCAD) + 'python.exe';
    if not FileExists(VerifiedFreeCAD) or not FileExists(PythonExe) then begin
      SuppressibleMsgBox('FreeCAD was not found. Install FreeCAD 1.1 or newer from freecad.org, or use Browse to select FreeCAD.exe.', mbError, MB_OK, IDOK);
      Result := False; Exit;
    end;
    EnsurePayload;
    WizardForm.StatusLabel.Caption := 'Verifying FreeCAD...';
    if not RunHelper('probe', '') then begin
      SuppressibleMsgBox(GetIniString('result', 'message', 'FreeCAD could not be verified. Repair FreeCAD or get help.', ResultFile), mbError, MB_OK, IDOK);
      Result := False;
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Extra, MenuFolder, DesktopFolder: String;
begin
  Result := '';
  if Installed then Exit;
  EnsurePayload;
  MenuFolder := ExpandConstant('{param:STARTMENUDIR|}');
  if MenuFolder = '' then MenuFolder := ExpandConstant('{userprograms}\CADWiz');
  DesktopFolder := ExpandConstant('{param:DESKTOPDIR|}');
  if DesktopFolder = '' then DesktopFolder := ExpandConstant('{userdesktop}');
  Extra := '--source ' + Quoted(ExpandConstant('{tmp}\payload\CADWiz')) + ' --start-menu ' + Quoted(MenuFolder);
  if DesktopChoice.Checked then Extra := Extra + ' --desktop ' + Quoted(DesktopFolder);
  WizardForm.StatusLabel.Caption := 'Verifying the offline connector and installing CADWiz...';
  if RunHelper('install', Extra) then Installed := True
  else Result := GetIniString('result', 'message', 'Setup stopped. Keep the setup log for support; your recovery copies are preserved.', ResultFile);
end;

function GetFreeCADExe(Param: String): String;
begin Result := ExtractFilePath(VerifiedFreeCAD) + 'pythonw.exe'; end;

function GetManager(Param: String): String;
begin Result := AddBackslash(DataFolder) + 'windows_wizard.py'; end;

function GetFreeCADDirectory(Param: String): String;
begin Result := ExtractFileDir(VerifiedFreeCAD); end;

function CanOpenFreeCAD: Boolean;
begin
  { Never launch another window if FreeCAD opened during the wizard. }
  Result := Installed and RunHelper('probe', '--require-closed');
end;
