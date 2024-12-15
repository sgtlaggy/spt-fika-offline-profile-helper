import json
import shutil
import sys
import zlib
from copy import deepcopy
from pathlib import Path
from tkinter import Tk, messagebox, ttk
from typing import Any, TypedDict
from urllib.parse import urljoin

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


TITLE = "Offline Profile Helper"

if getattr(sys, "frozen", False):  # PyInstaller-specific(?) check
    GAME_DIR = Path(sys.executable).parent
else:                              # not packed, just the script being run
    GAME_DIR = Path(__file__).parent
GAME_EXE = GAME_DIR / "EscapeFromTarkov.exe"

USER_PROFILES = GAME_DIR / "user" / "profiles"
FIKA_PROFILES = GAME_DIR / "user" / "fika"
LAUNCHER_CONFIG_FILE = GAME_DIR / "user" / "launcher" / "config.json"
LOCAL_CONFIG_FILE = LAUNCHER_CONFIG_FILE.with_suffix(".json.local")
REMOTE_CONFIG_FILE = LAUNCHER_CONFIG_FILE.with_suffix(".json.remote")

LOGIN_ENDPOINT = "/launcher/profile/login"
DOWNLOAD_ENDPOINT = "/fika/profile/download"
UPLOAD_ENDPOINT = "/helper/profile/upload"


ROOT = Tk()
ROOT.resizable(False, False)
ROOT.title(TITLE)

FRAME = ttk.Frame(ROOT, padding=2)
FRAME.grid()

DOWNLOAD_BUTTON = ttk.Button(FRAME, text="Download Profile", state="normal" if HAS_REQUESTS else "disabled")
DOWNLOAD_BUTTON.grid(column=0, row=0)
OVERWRITE_BUTTON = ttk.Button(FRAME, text="Overwrite Profile")
OVERWRITE_BUTTON.grid(column=0, row=1)
UPLOAD_BUTTON = ttk.Button(FRAME, text="Upload Profile", state="normal" if HAS_REQUESTS else "disabled")
UPLOAD_BUTTON.grid(column=0, row=2)

ttk.Label(FRAME, text="Current Server") \
   .grid(column=1, row=0)
SERVER_LABEL = ttk.Label(FRAME)
SERVER_LABEL.grid(column=1, row=1)
SWITCH_BUTTON = ttk.Button(FRAME, text="Switch Server")
SWITCH_BUTTON.grid(column=1, row=2)


class AutoLoginCreds(TypedDict):
    Username: str
    Password: str

class ServerConfig(TypedDict):
    Url: str
    AutoLoginCreds: AutoLoginCreds

class LauncherConfig(TypedDict):
    Server: ServerConfig


class LauncherConfigs:
    local: LauncherConfig
    remote: LauncherConfig
    current: LauncherConfig

    def __init__(self):
        if LOCAL_CONFIG_FILE.exists():
            self.local = load_json(LOCAL_CONFIG_FILE)
            self.current = self.remote = \
            load_json(LAUNCHER_CONFIG_FILE)
        elif REMOTE_CONFIG_FILE.exists():
            self.remote = load_json(REMOTE_CONFIG_FILE)
            self.current = self.local = \
            load_json(LAUNCHER_CONFIG_FILE)
        elif not LAUNCHER_CONFIG_FILE.exists():
            error('Launcher config file not found.', exit=True)
        else:  # first launch, no backup config files
            current = load_json(LAUNCHER_CONFIG_FILE)
            if '127.0.0.1' in current['Server']['Url']:
                error('Remote URL not set in launcher settings.', exit=True)
            self.current = self.remote = current
            self.local = deepcopy(current)
            self.local['Server']['Url'] = 'http://127.0.0.1:6969'
            LOCAL_CONFIG_FILE.write_text(json.dumps(self.local, indent=2))

        SWITCH_BUTTON.config(command=self.switch)


    def switch(self):
        if self.is_local:
            self.current = self.remote
            LAUNCHER_CONFIG_FILE.rename(LOCAL_CONFIG_FILE)
            REMOTE_CONFIG_FILE.rename(LAUNCHER_CONFIG_FILE)
        else:
            self.current = self.local
            LAUNCHER_CONFIG_FILE.rename(REMOTE_CONFIG_FILE)
            LOCAL_CONFIG_FILE.rename(LAUNCHER_CONFIG_FILE)
        update_server_label()

    @property
    def is_local(self) -> bool:
        return '127.0.0.1' in self.current['Server']['Url']


def error(message: str, *, retry=False, exit=False) -> bool | None:
    if retry:
        return messagebox.askretrycancel(TITLE, message)
    else:
        messagebox.showerror(TITLE, message)

    if exit:
        sys.exit()


def info(message: str):
    messagebox.showinfo(TITLE, message)


def update_server_label():
    if LAUNCHER_CONFIG.is_local:
        SERVER_LABEL["text"] = "local"
        SERVER_LABEL["foreground"] = "green"
    else:
        SERVER_LABEL["text"] = "remote"
        SERVER_LABEL["foreground"] = "blue"


def load_json(fp: Path):
    return json.loads(fp.read_text('utf-8'))


def compress(obj: dict) -> bytes:
    return zlib.compress(json.dumps(obj).encode())


def decompress(b: bytes) -> Any:
    return json.loads(zlib.decompress(b))


def find_profile(dir: Path) -> tuple[Path, dict] | tuple[None, None]:
    current_username = LAUNCHER_CONFIG.current["Server"]["AutoLoginCreds"]["Username"]
    if not dir.exists():
        return None, None

    for fp in dir.iterdir():
        if not fp.is_file():
            continue

        try:
            profile = load_json(fp)
        except Exception:
            continue
        if profile['info']['username'] == current_username:
            return fp, profile

    return None, None


def callback(btn: ttk.Button):
    def decorator(func):
        btn.config(command=func)
        return func
    return decorator


@callback(OVERWRITE_BUTTON)
def overwrite_profile():
    fp, _ = find_profile(FIKA_PROFILES)
    if fp is None:
        error("Fika profile not found.")
        return

    shutil.copy2(fp, USER_PROFILES)
    info("Local profile overwritten with downloaded profile.")


@callback(DOWNLOAD_BUTTON)
def download_profile():
    login_url = urljoin(LAUNCHER_CONFIG.remote["Server"]["Url"], LOGIN_ENDPOINT)
    download_url = urljoin(LAUNCHER_CONFIG.remote["Server"]["Url"], DOWNLOAD_ENDPOINT)

    creds: dict[str, str] = LAUNCHER_CONFIG.remote["Server"]["AutoLoginCreds"].copy()  # type: ignore
    creds['username'] = creds.pop('Username')
    creds['password'] = creds.pop('Password')

    while True:
        try:
            resp = requests.post(login_url, data=compress(creds), timeout=3)  # pyright: ignore[reportPossiblyUnboundVariable]
            break
        except (requests.Timeout, requests.ConnectionError):  # pyright: ignore[reportPossiblyUnboundVariable]
            retry = error("Cannot connect to remote server. Is it running?", retry=True)
            if not retry:
                return

    if not resp.ok:
        error("Server returned error on login.")
        return

    session_id: str = zlib.decompress(resp.content).decode()
    resp = requests.post(download_url, headers={"Cookie": f"PHPSESSID={session_id}"}, data=compress({}))  # pyright: ignore[reportPossiblyUnboundVariable]

    if not resp.ok:
        error("Server returned error trying to download. Is fika installed?")
        return

    profile = decompress(resp.content)
    fp = FIKA_PROFILES / f'{session_id}.json'
    fp.write_text(json.dumps(profile, indent='\t'))
    info("Profile downloaded successfully.")


@callback(UPLOAD_BUTTON)
def upload_profile():
    upload_url = urljoin(LAUNCHER_CONFIG.remote["Server"]["Url"], UPLOAD_ENDPOINT)

    _, profile = find_profile(USER_PROFILES)
    if profile is None:
        error("Failed to find local profile.")
        return

    while True:
        try:
            resp = requests.post(upload_url, data=compress(profile), timeout=3)  # pyright: ignore[reportPossiblyUnboundVariable]
            break
        except (requests.Timeout, requests.ConnectionError):  # pyright: ignore[reportPossiblyUnboundVariable]
            retry = error("Cannot connect to remote server. Is it running?", retry=True)
            if not retry:
                return

    resp_data: dict = decompress(resp.content)
    message: str | None = resp_data['message']
    if message is None:
        info("Profile uploaded successfully.")
    else:
        error(message)


if not GAME_EXE.exists():
    error('EscapeFromTarkov.exe not found.', exit=True)

LAUNCHER_CONFIG = LauncherConfigs()

update_server_label()
ROOT.mainloop()
