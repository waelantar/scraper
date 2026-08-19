@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
set "PYTHON_EXE=python"
if exist "%PROJECT_ROOT%.venv\Scripts\python.exe" set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"

if /I "%~1"=="setup" goto setup
if /I "%~1"=="crawl" goto crawl
if /I "%~1"=="console" goto console
if /I "%~1"=="agent" goto console
if /I "%~1"=="check" goto check
if /I "%~1"=="help" goto help
if "%~1"=="" goto console

echo Unknown command: %~1
goto help

:setup
python -m venv "%PROJECT_ROOT%.venv"
if errorlevel 1 exit /b 1
"%PROJECT_ROOT%.venv\Scripts\python.exe" -m pip install -r "%PROJECT_ROOT%requirements-dev.txt"
if errorlevel 1 exit /b 1
pushd "%PROJECT_ROOT%ts-cli" || exit /b 1
call npm.cmd ci
set "COMMAND_EXIT=%ERRORLEVEL%"
popd
exit /b %COMMAND_EXIT%

:crawl
shift
"%PYTHON_EXE%" -m python_engine crawl %*
exit /b %ERRORLEVEL%

:console
pushd "%PROJECT_ROOT%ts-cli" || exit /b 1
call npm.cmd run build
if errorlevel 1 (
    popd
    exit /b 1
)
node dist\agent.js
set "COMMAND_EXIT=%ERRORLEVEL%"
popd
exit /b %COMMAND_EXIT%

:check
"%PYTHON_EXE%" -m pytest -q --basetemp "%PROJECT_ROOT%.test-tmp" -p no:cacheprovider
if errorlevel 1 exit /b 1
pushd "%PROJECT_ROOT%ts-cli" || exit /b 1
call npm.cmd run type-check
if errorlevel 1 (
    popd
    exit /b 1
)
if exist "%PROJECT_ROOT%ts-cli\dist" rmdir /s /q "%PROJECT_ROOT%ts-cli\dist"
call npm.cmd run build
if errorlevel 1 (
    popd
    exit /b 1
)
node --test dist\*.test.js
set "COMMAND_EXIT=%ERRORLEVEL%"
popd
exit /b %COMMAND_EXIT%

:help
echo Polyglot Engine terminal commands
echo.
echo   polyglot setup
echo   polyglot crawl --seed URL [--max-depth N] [--max-urls N]
echo   polyglot [console^|agent]
echo   polyglot check
echo.
echo First time:
echo   .\polyglot.cmd setup
echo.
echo Crawl example:
echo   .\polyglot.cmd crawl --seed "https://books.toscrape.com/" --max-depth 2 --max-urls 100
echo.
echo Open the agent terminal:
echo   .\polyglot.cmd
exit /b 0
