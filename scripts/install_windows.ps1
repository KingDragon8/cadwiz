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
     the ChatGPT desktop app is set up, to its settings too -- after saving a
     copy of each.
  5. Adds CADWiz to the Start menu -- a CADWiz shortcut that opens FreeCAD and
     your assistant app together, and Uninstall CADWiz -- and, if you say yes, a
     CADWiz icon on the desktop.
  6. Says exactly what it changed.

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
    [string]$ClaudeConfig = "",
    [string]$CodexConfig = (Join-Path $env:USERPROFILE ".codex\config.toml"),
    [string]$FreeCADBin = "",
    [string]$StartMenuDir = (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\CADWiz"),
    [string]$DesktopDir = [Environment]::GetFolderPath("Desktop"),
    [string]$DataDir = (Join-Path $env:LOCALAPPDATA "CADWiz"),
    [switch]$Yes,
    [switch]$NoDesktop,
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
    # FreeCAD installs for everyone (Program Files) or "just for me" (the user's own
    # Programs folder); look in both.
    $found = @("$env:ProgramFiles\FreeCAD 1.*\bin\freecad.exe", "$env:LOCALAPPDATA\Programs\FreeCAD 1.*\bin\freecad.exe") |
        ForEach-Object { Get-ChildItem $_ -ErrorAction SilentlyContinue } |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($found) { $FreeCADBin = Split-Path -Parent $found.FullName }
}
$freecadOk = $false
$version = ""
if ($FreeCADBin -and (Test-Path -LiteralPath (Join-Path $FreeCADBin "freecad.exe"))) {
    # Ask FreeCAD itself ("FreeCAD 1.1.4 Revision: ..."): the folder name and the file's
    # version stamp are not reliable -- a portable FreeCAD_1.1.4-... folder has neither
    # in the expected form, and was refused (ORDER-2026-10-23-02).
    $cmd = Join-Path $FreeCADBin "freecadcmd.exe"
    if (Test-Path -LiteralPath $cmd) {
        $said = (& $cmd --version 2>$null | Select-Object -First 1)
        if ($said -match 'FreeCAD (\d+)\.(\d+)(\.\d+)?') { $version = $Matches[0] -replace '^FreeCAD ', '' }
    }
    if (-not $version) { $version = (Get-Item -LiteralPath (Join-Path $FreeCADBin "freecad.exe")).VersionInfo.ProductVersion }
    $freecadOk = ($version -match '^(1\.(1|[2-9])|[2-9]\.)') -or (-not $version -and $FreeCADBin -match 'FreeCAD[ _]1\.(1|[2-9])')
    Write-Host "FreeCAD found: $FreeCADBin (version $version)"
}
if (-not $freecadOk) {
    $what = if ($version) { "FreeCAD $version was found, but CADWiz needs FreeCAD 1.1 or newer." } else { "CADWiz needs FreeCAD 1.1 or newer, and it was not found on this computer." }
    Write-Host "$what Get the latest from $FreeCADDownload (free)." -ForegroundColor Yellow
    # Unattended runs (-Yes) never open a browser.
    if (-not $Yes -and (Ask "Open FreeCAD's official download page now? (You install it, then run this installer again.)")) {
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
    # An earlier CADWiz is kept OUTSIDE FreeCAD's Mod folder: FreeCAD loads every folder
    # in Mod, so a backup left there would still start with FreeCAD (ORDER-2026-10-23-02).
    $backups = Join-Path $DataDir "backups"
    $earlier = @(Get-Item -LiteralPath $target -ErrorAction SilentlyContinue) +
               @(Get-ChildItem -LiteralPath $ModDir -Directory -Filter "CADWiz.backup.*" -ErrorAction SilentlyContinue)
    foreach ($old in $earlier) {
        New-Item -ItemType Directory -Path $backups -Force | Out-Null
        $kept = Join-Path $backups "$($old.Name).$Stamp"
        Move-Item -LiteralPath $old.FullName -Destination $kept
        $Changed.Add("Moved your earlier CADWiz ($($old.Name)) out of FreeCAD, to $kept")
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
# Claude Desktop from claude.ai/download is a Microsoft Store (MSIX) app: it reads its
# settings from its own package folder, never from %APPDATA%\Claude. Writing only the
# %APPDATA% file left the founder's laptop red forever (ORDER-2026-10-23-02).
if (-not $ClaudeConfig) {
    $package = Get-ChildItem (Join-Path $env:LOCALAPPDATA "Packages") -Directory -Filter "Claude_*" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    $ClaudeConfig = if ($package) { Join-Path $package.FullName "LocalCache\Roaming\Claude\claude_desktop_config.json" }
                    else { Join-Path $env:APPDATA "Claude\claude_desktop_config.json" }
}
Write-Host "Claude Desktop's settings: $ClaudeConfig"
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

# ---- 4b. The ChatGPT desktop app (it keeps its tool settings in .codex\config.toml) ---------
if (Test-Path -LiteralPath $CodexConfig) {
    $codexText = Get-Content -Raw -LiteralPath $CodexConfig
    if ($codexText -match '(?m)^\[mcp_servers\.cadwiz\]') {
        $Changed.Add("The ChatGPT app already had CADWiz in its settings ($CodexConfig); left as it was")
    } else {
        $savedCodex = "$CodexConfig.before-cadwiz-$Stamp"
        Copy-Item -LiteralPath $CodexConfig -Destination $savedCodex
        $block = "`n[mcp_servers.cadwiz]`ncommand = '$FreeCADPython'`nargs = ['$server']`nstartup_timeout_sec = 60`n"
        [IO.File]::AppendAllText($CodexConfig, $block, (New-Object Text.UTF8Encoding $false))
        $Changed.Add("Saved a copy of the ChatGPT app's settings as $savedCodex")
        $Changed.Add("Added CADWiz to the ChatGPT app's settings ($CodexConfig)")
    }
} else {
    $Changed.Add("The ChatGPT desktop app is not set up on this computer, so only Claude was connected. Install it and run this again to use ChatGPT.")
}

# ---- 4c. the CADWiz shortcut, and how to uninstall -----------------------------------------
# One click on CADWiz opens FreeCAD and the assistant chosen in the panel together. It runs
# through FreeCAD's own windowless Python, so no console window flashes.
$Pythonw = Join-Path $FreeCADBin "pythonw.exe"
$Launch = Join-Path $AddonPath "src\integrations\cadwiz_plugin\launch.py"
$Icon = Join-Path $AddonPath "Resources\icons\cadwiz.ico"
$Shell = New-Object -ComObject WScript.Shell
function New-Shortcut([string]$Path, [string]$Target, [string]$Arguments, [string]$Description) {
    $link = $Shell.CreateShortcut($Path)
    $link.TargetPath = $Target
    $link.Arguments = $Arguments
    $link.WorkingDirectory = $FreeCADBin
    $link.Description = $Description
    if (Test-Path -LiteralPath $Icon) { $link.IconLocation = "$Icon,0" }
    $link.Save()
}
New-Item -ItemType Directory -Path $StartMenuDir, $DataDir -Force | Out-Null
$Uninstaller = Join-Path $DataDir "uninstall_windows.ps1"
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "uninstall_windows.ps1") -Destination $Uninstaller -Force
$Shortcuts = New-Object System.Collections.Generic.List[string]
$startLink = Join-Path $StartMenuDir "CADWiz.lnk"
New-Shortcut $startLink $Pythonw "`"$Launch`"" "Open FreeCAD with CADWiz, and your assistant app"
$Shortcuts.Add($startLink)
$uninstallLink = Join-Path $StartMenuDir "Uninstall CADWiz.lnk"
New-Shortcut $uninstallLink "powershell.exe" "-NoProfile -ExecutionPolicy Bypass -File `"$Uninstaller`"" "Remove CADWiz from this computer"
$Shortcuts.Add($uninstallLink)
$Changed.Add("Added CADWiz to the Start menu (CADWiz, and Uninstall CADWiz)")
if (-not $NoDesktop -and (Ask "Add a CADWiz icon to your desktop? It opens FreeCAD and your assistant app together.")) {
    $deskLink = Join-Path $DesktopDir "CADWiz.lnk"
    New-Shortcut $deskLink $Pythonw "`"$Launch`"" "Open FreeCAD with CADWiz, and your assistant app"
    $Shortcuts.Add($deskLink)
    $Changed.Add("Added a CADWiz icon to your desktop")
}
# What the uninstaller undoes -- exactly this, nothing else.
$record = [PSCustomObject]@{
    installed = (Get-Date).ToString("s"); addon = $(if ($SourceOnly) { "" } else { $AddonPath })
    claude_config = $ClaudeConfig; codex_config = $CodexConfig; shortcuts = @($Shortcuts); start_menu = $StartMenuDir
}
[IO.File]::WriteAllText((Join-Path $DataDir "install.json"), ($record | ConvertTo-Json -Depth 4), (New-Object Text.UTF8Encoding $false))

# ---- 5. what changed ----------------------------------------------------------------------
Write-Host ""
Write-Host "Done. What this installer changed:" -ForegroundColor Green
$Changed | ForEach-Object { Write-Host "  - $_" }
Write-Host ""
Write-Host "Next: click CADWiz in the Start menu (or on your desktop). It opens FreeCAD with the CADWiz panel, and your assistant app."
Write-Host "The light at the top of the panel turns green within a minute. Choose Claude or ChatGPT at the top of the panel."
Write-Host "To remove CADWiz later: Start menu > CADWiz > Uninstall CADWiz."
exit 0
