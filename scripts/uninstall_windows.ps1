# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
<#
.SYNOPSIS
  Removes CADWiz from this computer -- what install_windows.ps1 added, and nothing else.

.DESCRIPTION
  1. Asks first (unless -Yes).
  2. Removes the CADWiz shortcuts (Start menu, desktop).
  3. Removes the CADWiz folder from FreeCAD's Mod folder.
  4. Takes the CADWiz entry out of Claude Desktop's settings and the ChatGPT app's
     settings, after saving a copy of each. Every other entry is left as it was.
  5. KEEPS your work: your models, their saved versions and your CADWiz preferences
     stay where they are, and the closing message says where.

  Close FreeCAD, Claude Desktop and the ChatGPT app first. Start menu > CADWiz >
  Uninstall CADWiz, or double-click uninstall_windows.bat, or run:
    powershell -ExecutionPolicy Bypass -File scripts\uninstall_windows.ps1

.PARAMETER DataDir / Yes
  For tests: where the installer's record is kept, and answer yes.
#>
param(
    [string]$DataDir = (Join-Path $env:LOCALAPPDATA "CADWiz"),
    [switch]$Yes
)
$ErrorActionPreference = "Stop"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Changed = New-Object System.Collections.Generic.List[string]

Write-Host "CADWiz uninstaller" -ForegroundColor Cyan
$recordPath = Join-Path $DataDir "install.json"
if (-not (Test-Path -LiteralPath $recordPath)) {
    Write-Host "No CADWiz installation record was found ($recordPath). Nothing was changed."
    if (-not $Yes) { Read-Host "Press Enter to close" | Out-Null }
    exit 2
}
$record = Get-Content -Raw -LiteralPath $recordPath | ConvertFrom-Json
if (-not $Yes) {
    $answer = Read-Host "Remove CADWiz from this computer? Your models and their versions are kept. [y/N]"
    if ($answer -notmatch '^(y|yes)$') { Write-Host "Nothing was changed."; exit 1 }
}
if (Get-Process -Name freecad -ErrorAction SilentlyContinue) {
    Write-Host "FreeCAD is open. Close it, then run Uninstall CADWiz again. Nothing was changed." -ForegroundColor Yellow
    if (-not $Yes) { Read-Host "Press Enter to close" | Out-Null }
    exit 3
}

# ---- shortcuts ------------------------------------------------------------------------------
foreach ($link in @($record.shortcuts)) {
    if ($link -and $link -like "*.lnk" -and (Test-Path -LiteralPath $link)) {
        Remove-Item -LiteralPath $link -Force
        $Changed.Add("Removed the shortcut $link")
    }
}
if ($record.start_menu -and (Test-Path -LiteralPath $record.start_menu) -and
    -not (Get-ChildItem -LiteralPath $record.start_menu -Force)) {
    Remove-Item -LiteralPath $record.start_menu -Force
}

# ---- the addon ------------------------------------------------------------------------------
# Only a folder named CADWiz that holds CADWiz's own InitGui.py is removed.
$addon = [string]$record.addon
if ($addon -and (Split-Path -Leaf $addon) -eq "CADWiz" -and (Test-Path -LiteralPath (Join-Path $addon "InitGui.py"))) {
    Remove-Item -LiteralPath $addon -Recurse -Force
    $Changed.Add("Removed CADWiz from FreeCAD ($addon)")
}

# ---- Claude Desktop's settings ----------------------------------------------------------------
$claude = [string]$record.claude_config
if ($claude -and (Test-Path -LiteralPath $claude)) {
    $config = Get-Content -Raw -LiteralPath $claude | ConvertFrom-Json
    if ($config.mcpServers -and ($config.mcpServers.PSObject.Properties.Name -contains "cadwiz")) {
        Copy-Item -LiteralPath $claude -Destination "$claude.before-uninstall-$Stamp"
        $config.mcpServers.PSObject.Properties.Remove("cadwiz")
        [IO.File]::WriteAllText($claude, ($config | ConvertTo-Json -Depth 32), (New-Object Text.UTF8Encoding $false))
        $Changed.Add("Took CADWiz out of Claude Desktop's settings (a copy was saved as $claude.before-uninstall-$Stamp)")
    }
}

# ---- the ChatGPT app's settings ---------------------------------------------------------------
$codex = [string]$record.codex_config
if ($codex -and (Test-Path -LiteralPath $codex)) {
    $text = Get-Content -Raw -LiteralPath $codex
    # The installer's block: [mcp_servers.cadwiz] and its lines, up to the next table or the end.
    $without = [regex]::Replace($text, '(?ms)^\r?\n?\[mcp_servers\.cadwiz\]\r?\n(?:(?!\[).*\r?\n?)*', '')
    if ($without -ne $text) {
        Copy-Item -LiteralPath $codex -Destination "$codex.before-uninstall-$Stamp"
        [IO.File]::WriteAllText($codex, $without, (New-Object Text.UTF8Encoding $false))
        $Changed.Add("Took CADWiz out of the ChatGPT app's settings (a copy was saved as $codex.before-uninstall-$Stamp)")
    }
}

Remove-Item -LiteralPath $recordPath -Force
$self = Join-Path $DataDir "uninstall_windows.ps1"

Write-Host ""
Write-Host "Done. What this uninstaller changed:" -ForegroundColor Green
if ($Changed.Count) { $Changed | ForEach-Object { Write-Host "  - $_" } } else { Write-Host "  - nothing needed removing" }
Write-Host ""
Write-Host "Kept: your models and their saved versions, and your CADWiz preferences ($DataDir)."
Write-Host "FreeCAD, Claude Desktop and the ChatGPT app are not touched. To use CADWiz again, run its installer."
if (Test-Path -LiteralPath $self) { Remove-Item -LiteralPath $self -Force -ErrorAction SilentlyContinue }
if (-not $Yes) { Read-Host "Press Enter to close" | Out-Null }
exit 0
