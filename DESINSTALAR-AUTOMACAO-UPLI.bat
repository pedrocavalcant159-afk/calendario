@echo off
setlocal
title Desinstalador da Automacao UPLI
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0automation\uninstall.ps1"
exit /b %ERRORLEVEL%
