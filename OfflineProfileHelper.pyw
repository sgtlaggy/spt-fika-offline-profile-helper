# ruff: noqa: S310  # suppress warnings about urllib protocols
import json
import shutil
import ssl
import sys
import zlib
from copy import deepcopy
from pathlib import Path
from tkinter import Tk, messagebox, ttk
from typing import Any, TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


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

SELF_SIGNED_SSL = ssl.create_default_context()
SELF_SIGNED_SSL.check_hostname = False
SELF_SIGNED_SSL.verify_mode = ssl.CERT_NONE


ROOT = Tk()
ROOT.resizable(False, False)  # noqa: FBT003
ROOT.title(TITLE)

FRAME = ttk.Frame(ROOT, padding=2)
FRAME.grid()

DOWNLOAD_BUTTON = ttk.Button(FRAME, text="Download Profile")
DOWNLOAD_BUTTON.grid(column=0, row=0)
OVERWRITE_BUTTON = ttk.Button(FRAME, text="Overwrite Profile")
OVERWRITE_BUTTON.grid(column=0, row=1)
UPLOAD_BUTTON = ttk.Button(FRAME, text="Upload Profile")
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
            error('Launcher config file not found.')
            sys.exit()
        else:  # first launch, no backup config files
            current = load_json(LAUNCHER_CONFIG_FILE)
            if '127.0.0.1' in current['Server']['Url']:
                error('Remote URL not set in launcher settings.')
                sys.exit()
            self.current = self.remote = current
            self.local = deepcopy(current)
            self.local['Server']['Url'] = 'https://127.0.0.1:6969'
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


def error(message: str):
    messagebox.showerror(TITLE, message)


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


def compress_json(obj: dict) -> bytes:
    return zlib.compress(json.dumps(obj).encode())


def decompress_json(b: bytes) -> Any:
    return json.loads(zlib.decompress(b))


def _request(endpoint: str, *, data: dict | None = None,
            session_id: str | None = None) -> str | None:
    req = Request(urljoin(LAUNCHER_CONFIG.remote["Server"]["Url"], endpoint))
    req.data = compress_json(data or {})
    if session_id:
        req.add_header("Cookie", f"PHPSESSID={session_id}")

    try:
        resp = urlopen(req, timeout=3, context=SELF_SIGNED_SSL)
    except URLError:
        error("Failed to connect.\nIs the server running?")
    except TimeoutError:
        error("Request timed out.")
    except HTTPError as e:
        error(f"Server returned unexpected error {e.status}.")
    except Exception as e:
        error(f"Unknown error:\n{e}")
    else:
        return zlib.decompress(resp.read()).decode()


def login() -> tuple[int, str] | tuple[None, None]:
    orig_creds: dict[str, str] = LAUNCHER_CONFIG.remote["Server"]["AutoLoginCreds"]
    if orig_creds is None:
        error('Cannot find profile name, launcher is not logged in.')
        return

    creds = {
        'username': orig_creds['Username'],
        'password': orig_creds['Password']
    }

    data = _request(LOGIN_ENDPOINT, data=creds)

    if data is not None:
        return 200, data

    return None, None


def request(endpoint: str, *, data: dict | None = None,
            session_id: str | None = None) -> tuple[int, dict] | tuple[None, None]:
    resp = _request(endpoint, data=data, session_id=session_id)
    if resp is None:
        return None, None

    data = json.loads(resp)

    err = data.get('err')
    if err:
        return err, data.get('errmsg')

    return 200, data


def find_profile(dir: Path) -> tuple[Path, dict] | tuple[None, None]:  # noqa: A002
    current_username = LAUNCHER_CONFIG.current["Server"]["AutoLoginCreds"]["Username"]
    if not dir.exists():
        return None, None

    for fp in dir.iterdir():
        if not fp.is_file():
            continue

        try:
            profile = load_json(fp)
        except Exception:  # noqa: S112
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

    status, session_id = login()
    if status is None:
        return
    elif status != 200:
        error(f"Unexpected response:\n{status} {session_id}")
        return

    status, profile = request(DOWNLOAD_ENDPOINT, session_id=session_id)
    if status is None:
        return
    elif status == 404:
        error("Failed to download profile.\nIs Fika installed on the server?")
        return
    elif status != 200:
        error(f"Unexpected response:\n{status} {profile}")
        return

    fp = FIKA_PROFILES / f'{session_id}.json'
    fp.write_text(json.dumps(profile, indent='\t'))
    info("Profile downloaded successfully.")


@callback(UPLOAD_BUTTON)
def upload_profile():
    _, profile = find_profile(USER_PROFILES)
    if profile is None:
        error("Failed to find local profile.")
        return

    status, data = request(UPLOAD_ENDPOINT, data=profile)
    if status is None:
        return
    elif status == 404:
        error("Failed to upload profile.\nIs the server mod installed?")
        return
    elif status != 200:
        error(f"Unexpected response:\n{status} {data}")
        return

    message: str | None = data['message']
    if message is None:
        info("Profile uploaded successfully.")
    else:
        error(message)


if not GAME_EXE.exists():
    error('EscapeFromTarkov.exe not found.')
    sys.exit()

FIKA_PROFILES.mkdir(parents=True, exist_ok=True)
USER_PROFILES.mkdir(parents=True, exist_ok=True)
LAUNCHER_CONFIG = LauncherConfigs()

update_server_label()
ROOT.mainloop()
