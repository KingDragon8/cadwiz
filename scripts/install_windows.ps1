# SPDX-License-Identifier: LGPL-2.1-or-later
<# Double-click install_windows.bat. Works with Windows PowerShell 5.1 and PowerShell 7.
   No inline Python, pip installation, account changes or automatic application launch.
   Advanced fallback: -FreeCADBin <bin folder> -ModDir <verified user Mod folder>.
   -CheckOnly verifies discovery without installing. Close FreeCAD before installation.
#>
param(
    [string]$FreeCADBin='', [string]$ModDir='',
    [string]$DataDir=(Join-Path $env:LOCALAPPDATA 'CADWiz'),
    [string]$StartMenuDir=(Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\CADWiz'),
    [string]$DesktopDir=[Environment]::GetFolderPath('Desktop'),
    [switch]$Yes, [switch]$NoDesktop, [switch]$CheckOnly,
    [switch]$NoPip, [switch]$SourceOnly,
    [string]$ClaudeConfig='', [string]$CodexConfig=''
)
$ErrorActionPreference='Stop'
$helper=Join-Path $PSScriptRoot 'windows_installer.py'
$source=Join-Path (Split-Path -Parent $PSScriptRoot) 'CADWiz'
function Ask([string]$text) { if($Yes){return $true}; return (Read-Host ($text+' [y/N]')) -match '^(y|yes)$' }
function Invoke-Setup([string[]]$Arguments) {
    $output=[IO.Path]::GetTempFileName()
    try {
        $previous=$ErrorActionPreference
        try {
            $ErrorActionPreference='Continue'
            & $script:python $script:helper @Arguments --output-file $output | Out-Host
            $code=$LASTEXITCODE
        } finally { $ErrorActionPreference=$previous }
        $text=[IO.File]::ReadAllText($output,[Text.Encoding]::UTF8)
        if(-not $text.Trim()){throw 'FreeCAD Python did not return a setup result. Reinstall the official FreeCAD package and try again.'}
        $result=$text | ConvertFrom-Json
        if($code -ne 0 -or -not $result.ok){throw $result.message}
        return $result.result
    } finally { Remove-Item -LiteralPath $output -Force -ErrorAction SilentlyContinue }
}
try {
    Write-Host 'CADWiz Windows installer - offline, reversible setup' -ForegroundColor Cyan
    if(-not (Test-Path -LiteralPath $helper) -or -not (Test-Path -LiteralPath (Join-Path $source 'InitGui.py'))){
        throw 'The package is incomplete. Right-click the downloaded ZIP, choose Extract All, then run install_windows.bat from the extracted folder.'
    }
    if($SourceOnly){throw 'SourceOnly no longer changes assistant settings. Use -CheckOnly for discovery, or install normally and connect from CADWiz Setup.'}
    if(-not $FreeCADBin){
        $candidates=@("$env:ProgramFiles\FreeCAD 1.*\bin\FreeCAD.exe", "$env:LOCALAPPDATA\Programs\FreeCAD 1.*\bin\FreeCAD.exe") |
            ForEach-Object {Get-ChildItem -Path $_ -ErrorAction SilentlyContinue} | Sort-Object FullName -Descending
        if($candidates){$FreeCADBin=Split-Path -Parent ($candidates | Select-Object -First 1).FullName}
        elseif(-not $Yes){
            Add-Type -AssemblyName System.Windows.Forms
            $picker=New-Object Windows.Forms.OpenFileDialog
            $picker.Title='Select FreeCAD.exe from your supported FreeCAD installation'
            $picker.Filter='FreeCAD|FreeCAD.exe'
            if($picker.ShowDialog() -eq 'OK'){$FreeCADBin=Split-Path -Parent $picker.FileName}
        }
    }
    if(-not $FreeCADBin){throw 'FreeCAD 1.1 or newer was not found. Install it from https://www.freecad.org/downloads.php, then run this installer again.'}
    $python=Join-Path $FreeCADBin 'python.exe'
    if(-not (Test-Path -LiteralPath (Join-Path $FreeCADBin 'FreeCAD.exe')) -or -not (Test-Path -LiteralPath $python)){
        throw 'Select the FreeCAD bin folder containing FreeCAD.exe and python.exe. CADWiz does not need a separate Python installation.'
    }
    $info=Invoke-Setup @('discover')
    Write-Host ('FreeCAD verified: '+$info.version+' at '+$FreeCADBin)
    if(-not $ModDir){$ModDir=$info.mod_dir}
    if(-not $ModDir -and -not $Yes){
        Write-Host 'Automatic folder discovery failed. Open FreeCAD once first. If you know its user Mod directory, select it below.' -ForegroundColor Yellow
        Add-Type -AssemblyName System.Windows.Forms
        $picker=New-Object Windows.Forms.FolderBrowserDialog
        $picker.Description='Select the FreeCAD user Mod folder beside user.cfg, NOT Program Files'
        if($picker.ShowDialog() -eq 'OK'){$ModDir=$picker.SelectedPath}
    }
    if(-not $ModDir){throw 'Could not discover the user Mod folder. Open FreeCAD once, close it and retry. Advanced users can supply -ModDir; no scripts need editing.'}
    if($CheckOnly){Write-Host ('Discovery only; nothing installed. User Mod directory: '+$ModDir);exit 0}
    if(-not (Test-Path -LiteralPath (Join-Path $FreeCADBin 'pythonw.exe'))){throw 'FreeCAD pythonw.exe is missing. Repair the FreeCAD installation first.'}
    if(-not (Ask ('Install CADWiz into '+$ModDir+'? Existing verified CADWiz files will be backed up.'))){Write-Host 'Cancelled. Nothing installed.';exit 1}
    $target=Join-Path $ModDir 'CADWiz'
    $specs=@(
        @{path=(Join-Path $StartMenuDir 'CADWiz.lnk'); target=(Join-Path $FreeCADBin 'pythonw.exe'); arguments=('"'+(Join-Path $target 'src\integrations\cadwiz_plugin\launch.py')+'"'); description='Open FreeCAD with CADWiz'; working_directory=$FreeCADBin},
        @{path=(Join-Path $StartMenuDir 'Uninstall CADWiz.lnk'); target=(Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'); arguments=('-NoProfile -ExecutionPolicy Bypass -File "'+(Join-Path $DataDir 'uninstall_windows.ps1')+'" -DataDir "'+$DataDir+'"'); description='Uninstall CADWiz; keep models and preferences'; working_directory=$DataDir}
    )
    if(-not $NoDesktop -and (Ask 'Add a CADWiz desktop shortcut?')){
        if(-not $DesktopDir){throw 'Windows did not report a Desktop folder. Retry with -NoDesktop.'}
        $specs+=@{path=(Join-Path $DesktopDir 'CADWiz.lnk'); target=(Join-Path $FreeCADBin 'pythonw.exe'); arguments=('"'+(Join-Path $target 'src\integrations\cadwiz_plugin\launch.py')+'"'); description='Open FreeCAD with CADWiz'; working_directory=$FreeCADBin}
    }
    $plan=[IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($plan,(ConvertTo-Json -InputObject @($specs) -Depth 6),(New-Object Text.UTF8Encoding $false))
        $receipt=Invoke-Setup @('install','--source',$source,'--mod-dir',$ModDir,'--data-dir',$DataDir,'--shortcut-plan',$plan)
    } finally {Remove-Item -LiteralPath $plan -Force -ErrorAction SilentlyContinue}
    Write-Host ('CADWiz files installed and verified: '+$receipt.addon) -ForegroundColor Green
    if($receipt.backup){Write-Host ('Previous add-on kept at: '+$receipt.backup)}
    Write-Host 'No account settings were changed; no pip/network install was needed.'
    Write-Host 'Next: open FreeCAD. In CADWiz choose Setup, then your assistant connection. Startup and communication must still be verified.'
    exit 0
} catch {
    Write-Host ('CADWiz setup stopped: '+$_.Exception.Message) -ForegroundColor Red
    Write-Host 'Keep this message for support. Do not delete older installations or backups.'
    exit 1
}
