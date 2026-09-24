@echo off
rem Compatibility alias for the canonical two-process local render stack.
call "%~dp0CHAY_RENDER_LOCAL.bat" %*
exit /b %ERRORLEVEL%
