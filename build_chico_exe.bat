@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Building Chico.exe ...
python -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name "Chico" ^
  --icon "assets/icons/tanuki.ico" ^
  --add-data "assets/layers;assets/layers" ^
  --add-data "assets/icons;assets/icons" ^
  --add-data "fonts/Cubic_11.ttf;fonts" ^
  --add-data "fonts/OFL.txt;fonts" ^
  --hidden-import scipy.ndimage ^
  --hidden-import PIL._tkinter_finder ^
  --distpath "dist\Chico" ^
  chico_pet.pyw
if errorlevel 1 exit /b 1
if exist "unity\Build\ChicoGames.exe" (
  echo Copying Unity mini-games ...
  robocopy "unity\Build" "dist\Chico\unity\Build" /E /NFL /NDL /NJH /NJS /XF log.txt >nul
)
echo.
echo Done: dist\Chico\Chico.exe
exit /b 0
