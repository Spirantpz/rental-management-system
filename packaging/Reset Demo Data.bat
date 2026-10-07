@echo off
REM Backs up data and uploads to backups\<timestamp>\, then restores the demo data.
cd /d "%~dp0"
echo This will replace all current data with fresh demo data.
echo A backup of the current data is saved in the "backups" folder first.
echo Close RentalManagement before continuing.
set /p OK=Type YES to continue: 
if /i not "%OK%"=="YES" exit /b
RentalManagement.exe --reset-demo
pause
