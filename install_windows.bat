@echo off
rem Double-click to install CADWiz. Close FreeCAD and Claude Desktop first.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_windows.ps1" %*
pause
