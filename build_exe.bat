@echo off
REM Developer script: builds dist\RentalManagement\ (onedir). Run on Windows with Python installed.
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller || goto :error
python -m unittest discover -s tests -t . || goto :error
pyinstaller RentalManagement.spec --noconfirm --clean || goto :error
copy /y "packaging\Reset Demo Data.bat" "dist\RentalManagement\" >nul
copy /y README.md "dist\RentalManagement\" >nul
echo.
echo Build finished: dist\RentalManagement\RentalManagement.exe
pause
exit /b 0
:error
echo BUILD FAILED
pause
exit /b 1
