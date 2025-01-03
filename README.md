# Offline Profile Helper

Companion app for Fika players who can't or don't want to run their server 24/7 but still let some play solo. Can be used over internet, VPN, or LAN.

## How To Use

- Place the EXE in your SPT/Fika game folder.
- Have your usual Fika server URL in launcher settings on first launch.
- Only use this app with both launcher and server closed.

![screenshot](/screenshot.png)

Download Profile - download your profile, just like the button on the game's main menu. You can use this in case you forgot to download before closing your game

Overwrite Profile - copy your profile from `user/fika` to `user/profile` and overwrite it **without confirmation**

Upload Profile - upload your profile to the server so you don't need to send it to the server host manually and have them insert it before starting the server

Switch Server - switch your launcher config between your local server and friend's Fika server

### No EXE

Python scripts packed into executables will almost always be detected as malware, regardless of what they actually do. To use the program without the EXE, you can do the following:

1. Download the source code as a zip instead of the EXE
2. Extract the zip to a new folder and copy/move `OfflineProfileHelper.pyw` to your game folder
3. Download and install Python from [python.org](https://www.python.org/downloads/)

Optional, to enable the download/upload buttons:

4. Run `setup.bat` by double-clicking it **OR** run `py -m pip install requests` in command prompt

After that, you should be able to double-click `OfflineProfileHelper.pyw` to run it.
