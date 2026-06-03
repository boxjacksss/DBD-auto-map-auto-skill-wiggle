@echo off
setlocal
cd /d "%~dp0"

echo Starting DBD Python OCR Detector...
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python was not found.
  echo Install Python, then run this file again.
  pause
  exit /b 1
)

python -c "import mss; import PIL" >nul 2>nul
if errorlevel 1 (
  echo Installing Python dependencies...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo ERROR: Python dependency install failed.
    pause
    exit /b 1
  )
)

where tesseract >nul 2>nul
if errorlevel 1 (
  if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
    set "PATH=C:\Program Files\Tesseract-OCR;%PATH%"
  ) else (
    where winget >nul 2>nul
    if not errorlevel 1 (
      echo Tesseract OCR is missing, installing it now...
      winget install --id UB-Mannheim.TesseractOCR -e --source winget --accept-package-agreements --accept-source-agreements --silent
      if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" set "PATH=C:\Program Files\Tesseract-OCR;%PATH%"
    )
  )
)

python run.py

if errorlevel 1 (
  echo.
  echo The detector closed with an error.
  pause
)
