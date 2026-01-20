# Offline Profile Helper

Companion app for Fika players who can't or don't want to run their server 24/7 but still let some play solo. Can be used over internet, VPN, or LAN.

## How To Use

- Place the EXE/PYW in your SPT/Fika game folder alongside SPT shortcuts and EscapeFromTarkov.exe.
- Only use this app with the launcher closed.

![screenshot](/screenshot.png)

Download Profile - Download your profile from the current server, just like the button on the game's main menu. You can use this in case you forgot to download before closing your game.

Overwrite Profile - Copy your profile from `SPT/user/fika` to `SPT/user/profile` and overwrite it **without confirmation**.

Upload Profile - Upload your profile to the current server. This requires the Fika API Key to be set by editing the server data.

\+ - Add a new server to the list.

\- - Remove current server from the list.

Edit - Edit the current server data.

### No EXE

Python scripts packed into executables will almost always be detected as malware, regardless of what they actually do. To use the program without the EXE, you can do the following:

1. Download the `OfflineProfileHelper.pyw` file from latest release.
2. Download and install Python from [python.org](https://www.python.org/downloads/) (if using standalone and customizing install, it requires Tcl/Tk in optional features)
3. Double-click the `.pyw` to run it as you would the EXE.

To use on Linux, you can make the file executable (`chmod +x OfflineProfileHelper.pyw`) and change the first line from `pythonw3` to `python3`.
