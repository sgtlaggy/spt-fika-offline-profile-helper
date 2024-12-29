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

if not exist venv\ (
   py -m venv venv
)

call venv\Scripts\activate.bat

py -m pip install -Ur exe-requirements.txt
py -m PyInstaller -Fw OfflineProfileHelper.pyw
pause