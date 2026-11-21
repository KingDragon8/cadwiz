# SPDX-License-Identifier: LGPL-2.1-or-later
param([Parameter(Mandatory=$true)][string]$Plan)
$ErrorActionPreference='Stop'
$items=[IO.File]::ReadAllText($Plan,[Text.Encoding]::UTF8) | ConvertFrom-Json
$shell=New-Object -ComObject WScript.Shell
foreach($item in @($items)) {
    $link=$shell.CreateShortcut([string]$item.stage)
    $link.TargetPath=[string]$item.target
    $link.Arguments=[string]$item.arguments
    $link.WorkingDirectory=[string]$item.working_directory
    $link.Description=[string]$item.description
    if ($item.icon) { $link.IconLocation=[string]$item.icon }
    $link.Save()
}
