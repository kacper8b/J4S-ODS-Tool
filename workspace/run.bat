@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
set "PYTHONPATH=%PROJECT_ROOT%\src;%PYTHONPATH%"

pushd "%PROJECT_ROOT%" || exit /b 1
python -m j4s_ods_tool
set "EXIT_CODE=%ERRORLEVEL%"
popd

exit /b %EXIT_CODE%
