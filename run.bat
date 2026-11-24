@echo off
rem Oh-Brother launcher for Windows. Double-click it, or run it from a Command
rem Prompt with options, e.g.  run.bat --lan --no-browser
rem
rem Uses the bundled Python in runtime\windows-x86_64, which  sh build.sh
rem windows-x86_64  adds to the folder on Linux or macOS. Settings and
rem templates stay in the data folder beside this file, so the folder can live
rem on a thumbdrive. This file needs Windows line endings (see .gitattributes).

setlocal
set "HERE=%~dp0"
set "PLAT=windows-x86_64"
set "PY=%HERE%runtime\%PLAT%\python\python.exe"

if not exist "%PY%" goto noruntime
if not exist "%HERE%vendor\%PLAT%\" goto noruntime

rem Windows can be set not to run programs from removable drives. That's for
rem whoever looks after the PC to decide, so the app doesn't work around it
rem the way run.sh does on Linux: it says what to do instead.
"%PY%" -c "" >nul 2>&1
if errorlevel 1 goto blocked

rem -I: isolated mode (ignore host PYTHONPATH, user site-packages, etc.)
rem -B: don't write .pyc files onto the drive
"%PY%" -I -B "%HERE%app\main.py" --platform %PLAT% --data "%HERE%data" %*
if errorlevel 1 (
    rem Keep the window open, so the message can be read
    pause
    exit /b 1
)
exit /b 0

:noruntime
echo No runtime for %PLAT% in this folder. On Linux or macOS, run:
echo     sh build.sh %PLAT%
echo then copy the folder here again.
pause
exit /b 1

:blocked
echo Windows didn't start the Python that comes with Oh-Brother.
echo If this folder is on a thumbdrive, Windows may be set not to run programs
echo from it. Copy the whole folder to this PC, for example to Documents, and
echo start run.bat there. Not into Program Files: the app keeps your templates
echo and settings in its own folder.
pause
exit /b 1
