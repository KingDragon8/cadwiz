@echo off
rem Double-click to remove CADWiz. Your models and their versions are kept.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\uninstall_windows.ps1" %*
set "CADWizExit=%ERRORLEVEL%"
if not defined CADWIZ_NO_PAUSE pause
exit /b %CADWizExit%
