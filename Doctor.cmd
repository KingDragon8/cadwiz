@echo off
setlocal
title CADWiz Doctor - read-only checks
if exist "%ProgramFiles%\FreeCAD 1.1\bin\python.exe" (
  "%ProgramFiles%\FreeCAD 1.1\bin\python.exe" "%~dp0CADWiz\src\integrations\cadwiz_plugin\doctor.py" %*
) else (
  py -3 "%~dp0CADWiz\src\integrations\cadwiz_plugin\doctor.py" %*
)
if errorlevel 1 echo Doctor needs Python 3.11 or newer. It has not changed your files.
echo.
echo These are read-only checks. Startup and the assistant connection need separate verification.
pause
