@echo off
setlocal
title Atualizar Automacao UPLI
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0automation\install-new-pc.ps1" -SkipSetup
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo A atualizacao nao foi concluida. Consulte a mensagem acima.
  pause
)
exit /b %RESULT%
