# SPDX-License-Identifier: LGPL-2.1-or-later
param([string]$DataDir=(Join-Path $env:LOCALAPPDATA 'CADWiz'),[switch]$Yes)
$ErrorActionPreference='Stop'
try {
    $recordPath=Join-Path $DataDir 'install.json'
    if(-not (Test-Path -LiteralPath $recordPath)){Write-Host 'No CADWiz installation record found. Nothing removed.';exit 2}
    $record=[IO.File]::ReadAllText($recordPath,[Text.Encoding]::UTF8) | ConvertFrom-Json
    $helper=Join-Path $DataDir 'windows_installer.py'
    if($record.schema -ne 2 -or $record.product -ne 'CADWiz'){throw 'This legacy record cannot prove safe removal. Nothing removed; use FreeCAD Addon Manager.'}
    $expected=$record.managed_files.PSObject.Properties | Where-Object {$_.Name -eq $helper} | Select-Object -ExpandProperty Value
    if(-not $expected -or (Get-FileHash -LiteralPath $helper -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected){throw 'The uninstall helper changed or is missing. Nothing removed; use FreeCAD Addon Manager.'}
    $python=[string]$record.python
    if((Split-Path -Leaf $python) -ne 'python.exe' -or -not (Test-Path -LiteralPath $python)){throw 'FreeCAD Python is unavailable. Reinstall FreeCAD or use Addon Manager; saved files were kept.'}
    if(-not $Yes -and (Read-Host 'Remove CADWiz from FreeCAD and keep models/preferences? [y/N]') -notmatch '^(y|yes)$'){Write-Host 'Cancelled. Nothing removed.';exit 1}
    $output=[IO.Path]::GetTempFileName()
    try {
        & $python $helper uninstall --data-dir $DataDir --output-file $output
        $code=$LASTEXITCODE
        $result=[IO.File]::ReadAllText($output,[Text.Encoding]::UTF8) | ConvertFrom-Json
        if($code -ne 0 -or -not $result.ok){throw $result.message}
        Write-Host $result.result.message -ForegroundColor Green
        foreach($kept in @($result.result.preserved)){Write-Host ('Kept: '+$kept)}
    } finally {Remove-Item -LiteralPath $output -Force -ErrorAction SilentlyContinue}
    exit 0
} catch {Write-Host ('CADWiz uninstall stopped: '+$_.Exception.Message) -ForegroundColor Red;exit 1}
