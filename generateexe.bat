@echo off
setlocal
cd /d "%~dp0"

title M3U Stream Checker - Build EXE

echo ==========================================
echo      M3U STREAM CHECKER EXE BUILDER
echo ==========================================
echo.

set "PYTHON=py -3.10"
set "SCRIPT=m3u_stream_checker.py"
set "ICON=logo.ico"
set "APPNAME=M3U_Stream_Checker"

echo Checking Python 3.10...
%PYTHON% --version >nul 2>&1

if errorlevel 1 (
    echo Python 3.10 not found.
    echo Trying default Python...
    set "PYTHON=py"
)

echo.
echo Installing project requirements...
%PYTHON% -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo WARNING: Some requirements could not be installed.
    pause
)

echo.
echo Installing / updating PyInstaller...
%PYTHON% -m pip install --upgrade pyinstaller

if not exist "%SCRIPT%" (
    echo.
    echo ERROR:
    echo %SCRIPT% was not found in:
    echo %CD%
    pause
    exit /b 1
)

echo.
echo Cleaning old build files...

if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "%APPNAME%.spec" del /q "%APPNAME%.spec"

echo.
echo Building executable...

if exist "%ICON%" (
    echo Using icon: %ICON%

    %PYTHON% -m PyInstaller ^
        --noconfirm ^
        --clean ^
        --onefile ^
        --windowed ^
        --name "%APPNAME%" ^
        --icon "%ICON%" ^
        "%SCRIPT%"
) else (
    echo.
    echo WARNING: logo.ico was not found.
    echo Building EXE without custom icon.
    echo.

    %PYTHON% -m PyInstaller ^
        --noconfirm ^
        --clean ^
        --onefile ^
        --windowed ^
        --name "%APPNAME%" ^
        "%SCRIPT%"
)

if errorlevel 1 (
    echo.
    echo ==========================================
    echo BUILD FAILED
    echo ==========================================
    pause
    exit /b 1
)

echo.
echo ==========================================
echo BUILD SUCCESSFUL
echo ==========================================
echo.
echo EXE created at:
echo %CD%\dist\%APPNAME%.exe
echo.

explorer "%CD%\dist"

pause
endlocal