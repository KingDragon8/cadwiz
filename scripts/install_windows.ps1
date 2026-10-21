# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (C) 2026 Steve Gregerson / WizLabs
<#
.SYNOPSIS
  Installs CADWiz into FreeCAD and connects it to Claude Desktop.

.DESCRIPTION
  1. Checks for FreeCAD 1.1. If it is missing or older, it ASKS whether to open
     FreeCAD's official download page -- it never downloads anything by itself.
  2. Copies the CADWiz folder into FreeCAD's Mod folder (an older CADWiz there is
     kept, renamed CADWiz.backup.<date>).
  3. Installs the one package the Claude connection needs (mcp 1.27) into
     FreeCAD's own Python.
  4. Connects the AI app you use: adds CADWiz to Claude Desktop's settings and, if
     OpenAI's Codex app is set up (ChatGPT), to its settings too -- after saving a
     copy of each.
  5. Says exactly what it changed.

  Close FreeCAD and Claude Desktop first. Double-click install_windows.bat, or run:
    powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1

.PARAMETER SourceOnly
  For developers: do not copy anything into FreeCAD; point Claude Desktop at the
  CADWiz folder in this checkout instead.
.PARAMETER ModDir / ClaudeConfig / FreeCADBin / Yes
  For tests: where FreeCAD's Mod folder and Claude's settings file are, where
  FreeCAD is installed, and answer yes to the questions.
#>
param(
    [switch]$SourceOnly,
    [string]$ModDir = (Join-Path $env:APPDATA "FreeCAD\v1-1\Mod"),
    [string]$ClaudeConfig = (Join-Path $env:APPDATA "Claude\claude_desktop_config.json"),
    [string]$CodexConfig = (Join-Path $env:USERPROFILE ".codex\config.toml"),
    [string]$FreeCADBin = "",
    [switch]$Yes,
    [switch]$NoPip
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Source = Join-Path $Repo "CADWiz"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Changed = New-Object System.Collections.Generic.List[string]
$FreeCADDownload = "https://www.freecad.org/downloads.php"

function Ask([string]$Question) {
    if ($Yes) { return $true }
    $answer = Read-Host "$Question [y/N]"
    return $answer -match '^(y|yes)$'
}

Write-Host "CADWiz installer" -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath (Join-Path $Source "InitGui.py"))) { throw "The CADWiz folder was not found next to this script ($Source)." }

# ---- 1. FreeCAD 1.1 -------------------------------------------------------------------
if (-not $FreeCADBin) {
    $found = Get-ChildItem "C:\Program Files\FreeCAD 1.*\bin\freecad.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($found) { $FreeCADBin = Split-Path -Parent $found.FullName }
}
$freecadOk = $false
if ($FreeCADBin -and (Test-Path -LiteralPath (Join-Path $FreeCADBin "freecad.exe"))) {
    $version = (Get-Item -LiteralPath (Join-Path $FreeCADBin "freecad.exe")).VersionInfo.ProductVersion
    $freecadOk = ($FreeCADBin -match 'FreeCAD 1\.(1|[2-9])') -or ($version -match '^1\.(1|[2-9])')
    Write-Host "FreeCAD found: $FreeCADBin ($version)"
}
if (-not $freecadOk) {
    Write-Host "CADWiz needs FreeCAD 1.1 or newer, and it was not found on this computer." -ForegroundColor Yellow
    if (Ask "Open FreeCAD's official download page now? (You install it, then run this installer again.)") {
        Start-Process $FreeCADDownload
        Write-Host "Opened $FreeCADDownload. Install FreeCAD 1.1, then run this installer again."
    } else {
        Write-Host "Nothing was changed. Install FreeCAD 1.1 from $FreeCADDownload, then run this installer again."
    }
    exit 2
}
$FreeCADPython = Join-Path $FreeCADBin "python.exe"

# ---- 2. the addon -----------------------------------------------------------------------
$AddonPath = $Source
if (-not $SourceOnly) {
    New-Item -ItemType Directory -Path $ModDir -Force | Out-Null
    $target = Join-Path $ModDir "CADWiz"
    if (Test-Path -LiteralPath $target) {
        $kept = Join-Path $ModDir "CADWiz.backup.$Stamp"
        Move-Item -LiteralPath $target -Destination $kept
        $Changed.Add("Kept your earlier CADWiz as $kept")
    }
    Copy-Item -LiteralPath $Source -Destination $target -Recurse
    Get-ChildItem -LiteralPath $target -Directory -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force
    $AddonPath = $target
    $Changed.Add("Installed CADWiz into $target")
}

# ---- 3. the one package the Claude connection needs ------------------------------------
if (-not $NoPip) {
    Write-Host "Installing the Claude connection package (mcp 1.27) into FreeCAD's Python..."
    & $FreeCADPython -m pip install --user --disable-pip-version-check --quiet "mcp==1.27.0"
    if ($LASTEXITCODE -ne 0) { throw "Installing mcp into FreeCAD's Python failed (see above). Nothing else was changed after this point." }
    $Changed.Add("Installed mcp 1.27 into FreeCAD's Python ($FreeCADPython)")
}

# ---- 4. Claude Desktop's settings ---------------------------------------------------------
$server = Join-Path $AddonPath "src\integrations\cadwiz_plugin\server.py"
$configDir = Split-Path -Parent $ClaudeConfig
New-Item -ItemType Directory -Path $configDir -Force | Out-Null
if (Test-Path -LiteralPath $ClaudeConfig) {
    $saved = "$ClaudeConfig.before-cadwiz-$Stamp"
    Copy-Item -LiteralPath $ClaudeConfig -Destination $saved
    $Changed.Add("Saved a copy of Claude Desktop's settings as $saved")
    $raw = Get-Content -Raw -LiteralPath $ClaudeConfig
    $config = if ($raw.Trim()) { $raw | ConvertFrom-Json } else { New-Object PSObject }
} else {
    $config = New-Object PSObject
}
if (-not ($config.PSObject.Properties.Name -contains "mcpServers")) {
    $config | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue (New-Object PSObject)
}
$entry = [PSCustomObject]@{ command = $FreeCADPython; args = @($server) }
$config.mcpServers | Add-Member -NotePropertyName "cadwiz" -NotePropertyValue $entry -Force
$json = $config | ConvertTo-Json -Depth 32
[IO.File]::WriteAllText($ClaudeConfig, $json, (New-Object Text.UTF8Encoding $false))
$Changed.Add("Added CADWiz to Claude Desktop's settings ($ClaudeConfig)")

# ---- 4b. ChatGPT, through OpenAI's Codex app (signed in with a ChatGPT account) -------------
if (Test-Path -LiteralPath $CodexConfig) {
    $codexText = Get-Content -Raw -LiteralPath $CodexConfig
    if ($codexText -match '(?m)^\[mcp_servers\.cadwiz\]') {
        $Changed.Add("ChatGPT (Codex) already had CADWiz in its settings ($CodexConfig); left as it was")
    } else {
        $savedCodex = "$CodexConfig.before-cadwiz-$Stamp"
        Copy-Item -LiteralPath $CodexConfig -Destination $savedCodex
        $block = "`n[mcp_servers.cadwiz]`ncommand = '$FreeCADPython'`nargs = ['$server']`nstartup_timeout_sec = 60`n"
        [IO.File]::AppendAllText($CodexConfig, $block, (New-Object Text.UTF8Encoding $false))
        $Changed.Add("Saved a copy of ChatGPT/Codex's settings as $savedCodex")
        $Changed.Add("Added CADWiz to ChatGPT/Codex's settings ($CodexConfig)")
    }
} else {
    $Changed.Add("ChatGPT/Codex is not set up on this computer, so only Claude was connected. Install Codex and run this again to use ChatGPT.")
}

# ---- 5. what changed ----------------------------------------------------------------------
Write-Host ""
Write-Host "Done. What this installer changed:" -ForegroundColor Green
$Changed | ForEach-Object { Write-Host "  - $_" }
Write-Host ""
Write-Host "Next: open FreeCAD (the CADWiz panel appears on the right), then open Claude Desktop or Codex."
Write-Host "The light at the top of the panel turns green within a minute. Choose Claude or ChatGPT at the top of the panel."
exit 0
