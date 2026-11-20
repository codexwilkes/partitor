; SPDX-License-Identifier: AGPL-3.0-or-later
; Copyright (C) 2026 Nathan Wilkes and partitor contributors
;
; Inno Setup 6 script of the Windows installer (platforms/windows/README.md, "Installer").
; build-windows.py --installer runs it:  ISCC /DAppVersion=<VERSION> /DDistDir=<dist\partitor> partitor.iss
;
; Per user, no admin: the program goes to %LOCALAPPDATA%\Programs\partitor, `partitor` goes on the
; PATH of the user, a Start menu entry opens the menu. A wizard page asks for the library folder
; (default Documents\partitor); the installer makes inbox\ and library\ in it and sets the user
; variable PARTITOR_LIBRARY. Uninstall removes the program, the PATH entry and the variable;
; it never removes the library.

#ifndef AppVersion
  #error Give /DAppVersion=<version>
#endif
#ifndef DistDir
  #define DistDir "..\..\..\dist\partitor"
#endif

[Setup]
AppId={{6F0D3C2E-8B4A-4E57-9C1D-2A7B5E9F4C31}
AppName=partitor
AppVersion={#AppVersion}
AppPublisher=partitor contributors
AppPublisherURL=https://github.com/codexwilkes/partitor
DefaultDirName={autopf}\partitor
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
ChangesEnvironment=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\..\dist
OutputBaseFilename=partitor-{#AppVersion}-setup
LicenseFile={#DistDir}\LICENSE
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
UninstallDisplayName=partitor {#AppVersion}
UninstallDisplayIcon={app}\partitor.exe
SetupIconFile=partitor.ico

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Dirs]
Name: "{code:LibDir}\inbox"; Flags: uninsneveruninstall
Name: "{code:LibDir}\library"; Flags: uninsneveruninstall

[Icons]
Name: "{userprograms}\partitor"; Filename: "{app}\partitor.exe"; WorkingDir: "{code:LibDir}"; \
  Comment: "partitor menu"

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: string; ValueName: "PARTITOR_LIBRARY"; \
  ValueData: "{code:LibDir}"; Flags: uninsdeletevalue

[Code]
var
  LibPage: TInputDirWizardPage;

function LibDir(Param: String): String;
begin
  Result := LibPage.Values[0];
end;

procedure InitializeWizard;
var
  Current: String;
begin
  LibPage := CreateInputDirPage(wpSelectDir, 'Library folder',
    'Where does partitor keep your scores and parts?',
    'partitor makes the folders inbox and library here. A folder on a network share is possible. ' +
    'Uninstall never removes this folder.', False, '');
  LibPage.Add('');
  Current := GetEnv('PARTITOR_LIBRARY');
  if Current = '' then
    Current := ExpandConstant('{userdocs}\partitor');
  LibPage.Values[0] := Current;
end;

// The user PATH: add the program folder once on install, remove it on uninstall.
function PathKey: String;
begin
  Result := 'Environment';
end;

function HasPathEntry(Path, Entry: String): Boolean;
begin
  Result := Pos(';' + Uppercase(Entry) + ';', ';' + Uppercase(Path) + ';') > 0;
end;

procedure AddToPath;
var
  Path: String;
begin
  if not RegQueryStringValue(HKCU, PathKey, 'Path', Path) then
    Path := '';
  if HasPathEntry(Path, ExpandConstant('{app}')) then
    exit;
  if (Path <> '') and (Copy(Path, Length(Path), 1) <> ';') then
    Path := Path + ';';
  RegWriteExpandStringValue(HKCU, PathKey, 'Path', Path + ExpandConstant('{app}'));
end;

procedure RemoveFromPath;
var
  Path, Entry: String;
  P: Integer;
begin
  if not RegQueryStringValue(HKCU, PathKey, 'Path', Path) then
    exit;
  Entry := ExpandConstant('{app}');
  Path := ';' + Path + ';';
  P := Pos(';' + Uppercase(Entry) + ';', Uppercase(Path));
  if P = 0 then
    exit;
  Delete(Path, P, Length(Entry) + 1);
  Path := Copy(Path, 2, Length(Path) - 2);
  RegWriteExpandStringValue(HKCU, PathKey, 'Path', Path);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    AddToPath;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveFromPath;
end;
