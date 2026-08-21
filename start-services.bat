@echo off
setlocal enabledelayedexpansion

REM Runs start-services.sh via Git Bash.
REM
REM Usage (double-click, or from cmd/PowerShell):
REM   start-services.bat              start all services with --reload
REM   start-services.bat --no-reload  start without auto-reload
REM   start-services.bat --stop       stop everything

set "SCRIPT_DIR=%~dp0"
set "SH_SCRIPT=%SCRIPT_DIR%start-services.sh"

if not exist "%SH_SCRIPT%" (
    echo ERROR: Could not find start-services.sh next to this file.
    echo   Expected at: %SH_SCRIPT%
    goto :fail
)

REM Find Git Bash: check the usual install locations, then fall back to PATH.
set "BASH_EXE="
if exist "%ProgramFiles%\Git\bin\bash.exe"      set "BASH_EXE=%ProgramFiles%\Git\bin\bash.exe"
if not defined BASH_EXE if exist "%ProgramFiles%\Git\usr\bin\bash.exe"     set "BASH_EXE=%ProgramFiles%\Git\usr\bin\bash.exe"
if not defined BASH_EXE if exist "%ProgramFiles(x86)%\Git\bin\bash.exe"    set "BASH_EXE=%ProgramFiles(x86)%\Git\bin\bash.exe"
if not defined BASH_EXE if exist "%LOCALAPPDATA%\Programs\Git\bin\bash.exe" set "BASH_EXE=%LOCALAPPDATA%\Programs\Git\bin\bash.exe"

if not defined BASH_EXE (
    for /f "delims=" %%I in ('where bash 2^>nul') do (
        if not defined BASH_EXE set "BASH_EXE=%%I"
    )
)

if not defined BASH_EXE (
    echo ERROR: Git Bash not found.
    echo   Install Git for Windows from https://git-scm.com/download/win
    echo   or add bash.exe to your PATH.
    goto :fail
)

"%BASH_EXE%" "%SH_SCRIPT%" %*
set "EXIT_CODE=%ERRORLEVEL%"

REM Keep the window open on failure when double-clicked from Explorer.
if not "%EXIT_CODE%"=="0" (
    echo.
    echo Script exited with code %EXIT_CODE%.
    if /i "%~1"=="" pause
)

endlocal & exit /b %EXIT_CODE%

:fail
echo.
pause
endlocal & exit /b 1
