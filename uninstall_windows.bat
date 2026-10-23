@echo off
rem Double-click to remove CADWiz. Your models and their versions are kept.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\uninstall_windows.ps1" %*
