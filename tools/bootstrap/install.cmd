@echo off
REM Thin wrapper around install.ps1.
REM
REM -NoProfile / -ExecutionPolicy Bypass so a locked-down machine can still run a
REM LOCAL, self-contained script. Nothing here reaches the network: every byte the
REM install needs is already in this bundle.
setlocal
set "HERE=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%install.ps1" %*
exit /b %ERRORLEVEL%