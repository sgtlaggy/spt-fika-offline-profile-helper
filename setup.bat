@echo off

where /q py
if errorlevel 1 (
   echo Python is not installed or `py` launcher is not available in PATH.

   choice /m "Open python.org to download now"
   if errorlevel 1 (
      start "" https://python.org/downloads
   )

   exit /B
)

py -m pip install -r requirements.txt

echo
echo All set up and ready to go!
pause