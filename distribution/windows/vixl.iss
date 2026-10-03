#ifndef VixlVersion
  #error VixlVersion is required
#endif
#ifndef SourceRoot
  #define SourceRoot "..\.."
#endif
[Setup]
AppId={{B0F6895F-05DA-4E86-A2CD-23D298519493}
AppName=Vixl
AppVersion={#VixlVersion}
AppPublisher=Vixl contributors
AppPublisherURL=https://github.com/jxburros/Vixl
AppSupportURL=https://github.com/jxburros/Vixl/issues
AppUpdatesURL=https://github.com/jxburros/Vixl/releases
DefaultDirName={localappdata}\Programs\Vixl
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#SourceRoot}\dist\release
OutputBaseFilename=Vixl-Setup-{#VixlVersion}-windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes
CloseApplications=no
RestartApplications=no
UninstallDisplayName=Vixl

[Files]
Source: "{#SourceRoot}\dist\launcher\vixl.exe"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "{#SourceRoot}\dist\runtime\vixl-engine\*"; DestDir: "{app}\versions\{#VixlVersion}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Vixl"; Filename: "{app}\bin\vixl.exe"; WorkingDir: "{userdocs}"
Name: "{userprograms}\Uninstall Vixl"; Filename: "{uninstallexe}"

[UninstallDelete]
; Only installer-managed data. User projects and AI configuration are never removed.
Type: filesandordirs; Name: "{app}\versions"
Type: filesandordirs; Name: "{app}\update-work"
Type: files; Name: "{app}\install.json"
Type: files; Name: "{app}\.update.lock"
Type: files; Name: "{app}\.vixl-*.tmp"

[Code]
function WithoutVixlPath(Value: String): String;
var
  BinPath: String;
  StartAt, EndAt: Integer;
begin
  Result := Value;
  BinPath := ExpandConstant('{app}\bin');
  StartAt := 1;
  while StartAt <= Length(Result) do
  begin
    EndAt := StartAt;
    while (EndAt <= Length(Result)) and (Result[EndAt] <> ';') do EndAt := EndAt + 1;
    if CompareText(RemoveBackslashUnlessRoot(Trim(Copy(Result, StartAt, EndAt - StartAt))), BinPath) = 0 then
    begin
      if EndAt <= Length(Result) then
        Delete(Result, StartAt, EndAt - StartAt + 1)
      else if StartAt > 1 then
        Delete(Result, StartAt - 1, EndAt - StartAt + 1)
      else Result := '';
    end
    else StartAt := EndAt + 1;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
  ExistingPath, UpdatedPath: String;
begin
  if CurStep = ssPostInstall then
  begin
    if not Exec(ExpandConstant('{app}\bin\vixl.exe'), '--vixl-install {#VixlVersion}',
                ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code) then
      RaiseException('Vixl could not initialize. Please run the installer again.');
    if Code <> 0 then
      RaiseException('Vixl did not pass its installation check. Your previous version was kept.');
    RegQueryStringValue(HKCU, 'Environment', 'Path', ExistingPath);
    UpdatedPath := ExpandConstant('{app}\bin');
    ExistingPath := WithoutVixlPath(ExistingPath);
    if ExistingPath <> '' then UpdatedPath := UpdatedPath + ';' + ExistingPath;
    if not RegWriteExpandStringValue(HKCU, 'Environment', 'Path', UpdatedPath) then
      RaiseException('Could not update your user PATH.');
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ExistingPath: String;
begin
  if CurUninstallStep = usPostUninstall then
    if RegQueryStringValue(HKCU, 'Environment', 'Path', ExistingPath) then
      RegWriteExpandStringValue(HKCU, 'Environment', 'Path', WithoutVixlPath(ExistingPath));
end;
