@echo off
setlocal
title Instalador da Automacao UPLI
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0automation\install-new-pc.ps1"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo A instalacao nao foi concluida. Consulte a mensagem acima.
  pause
)
exit /b %RESULT%
