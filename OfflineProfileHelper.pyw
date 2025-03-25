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
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


TITLE = "Offline Profile Helper"

if getattr(sys, "frozen", False):  # PyInstaller-specific(?) check
    GAME_DIR = Path(sys.executable).parent
else:                              # not packed, just the script being run
    GAME_DIR = Path(__file__).parent
GAME_EXE = GAME_DIR / "EscapeFromTarkov.exe"

USER_PROFILES = GAME_DIR / "user" / "profiles"
FIKA_PROFILES = GAME_DIR / "user" / "fika"


class AutoLoginCreds(TypedDict):
    Username: str
    Password: str

class ServerConfig(TypedDict):
    Url: str
    AutoLoginCreds: AutoLoginCreds

class LauncherConfig(TypedDict):
    Server: ServerConfig


class LauncherConfigs:
    CONFIG_FILE = GAME_DIR / "user" / "launcher" / "config.json"
    LOCAL_FILE = CONFIG_FILE.with_suffix(".json.local")
    REMOTE_FILE = CONFIG_FILE.with_suffix(".json.remote")

    local: LauncherConfig
    remote: LauncherConfig
    current: LauncherConfig

    def __init__(self):
        if self.LOCAL_FILE.exists():
            self.local = load_json(self.LOCAL_FILE)
            self.remote = load_json(self.CONFIG_FILE)
            self.current = self.remote
        elif self.REMOTE_FILE.exists():
            self.local = load_json(self.CONFIG_FILE)
            self.remote = load_json(self.REMOTE_FILE)
            self.current = self.local
        elif not self.CONFIG_FILE.exists():
            error('Launcher config file not found.')
            sys.exit()
        else:  # first launch, no backup config files
            current = load_json(self.CONFIG_FILE)
            if '127.0.0.1' in current['Server']['Url']:
                error('Remote URL not set in launcher settings.')
                sys.exit()

            self.current = self.remote = current
            self.local = deepcopy(current)

            url = urlparse(self.local['Server']['Url'])
            self.local['Server']['Url'] = f'{url.scheme}://127.0.0.1:6969'

            self.LOCAL_FILE.write_text(json.dumps(self.local, indent=2))

    def switch(self):
        if self.is_local:
            self.current = self.remote
            self.CONFIG_FILE.rename(self.LOCAL_FILE)
            self.REMOTE_FILE.rename(self.CONFIG_FILE)
        else:
            self.current = self.local
            self.CONFIG_FILE.rename(self.REMOTE_FILE)
            self.LOCAL_FILE.rename(self.CONFIG_FILE)

    @property
    def is_local(self) -> bool:
        return '127.0.0.1' in self.current['Server']['Url']


class HTTP:
    LOGIN_ENDPOINT = "/launcher/profile/login"
    DOWNLOAD_ENDPOINT = "/fika/profile/download"
    UPLOAD_ENDPOINT = "/helper/profile/upload"

    def __init__(self):
        self._ssl = ssl.create_default_context()
        self._ssl.check_hostname = False
        self._ssl.verify_mode = ssl.CERT_NONE

    @staticmethod
    def compress_json(obj: dict) -> bytes:
        return zlib.compress(json.dumps(obj).encode())

    @staticmethod
    def decompress_json(b: bytes) -> Any:
        return json.loads(zlib.decompress(b))

    def _request(self, url: str, *, data: dict | None = None,
                session_id: str | None = None) -> str | None:
        req = Request(url)
        req.data = self.compress_json(data or {})
        if session_id:
            req.add_header("Cookie", f"PHPSESSID={session_id}")

        try:
            resp = urlopen(req, timeout=3, context=self._ssl)
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

    def login(self, server_url: str, credentials: AutoLoginCreds) \
            -> tuple[int, str] | tuple[None, None]:
        if credentials is None:
            error('Cannot find profile name, launcher is not logged in.')
            return

        creds = {
            'username': credentials['Username'],
            'password': credentials['Password']
        }

        url = urljoin(server_url, self.LOGIN_ENDPOINT)
        data = self._request(url, data=creds)

        if data is not None:
            return 200, data

        return None, None

    def request(self, url: str, *, data: dict | None = None,
                session_id: str | None = None) -> tuple[int, dict] | tuple[None, None]:
        resp = self._request(url, data=data, session_id=session_id)
        if resp is None:
            return None, None

        data = json.loads(resp)

        err = data.get('err')
        if err:
            return err, data.get('errmsg')

        return 200, data


class MainWindow(Tk):
    def __init__(self):
        super().__init__()
        self.http = HTTP()
        self.launcher_config = LauncherConfigs()

        self.resizable(False, False)  # noqa: FBT003
        self.title(TITLE)

        frame = ttk.Frame(self, padding=2)
        frame.grid()

        ttk.Button(frame, text="Download Profile", command=self.download_profile) \
           .grid(column=0, row=0)
        ttk.Button(frame, text="Overwrite Profile", command=self.overwrite_profile) \
           .grid(column=0, row=1)
        ttk.Button(frame, text="Upload Profile", command=self.upload_profile) \
           .grid(column=0, row=2)

        ttk.Label(frame, text="Current Server") \
           .grid(column=1, row=0)
        self.server_label = ttk.Label(frame)
        self.server_label.grid(column=1, row=1)
        ttk.Button(frame, text="Switch Server", command=self.change_launcher_config) \
            .grid(column=1, row=2)

        self.update_server_label()

    def _find_profile(self, dir: Path) -> tuple[Path, dict] | tuple[None, None]:  # noqa: A002
        current_username = self.launcher_config.current["Server"]["AutoLoginCreds"]["Username"]
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

    def overwrite_profile(self):
        fp, _ = self._find_profile(FIKA_PROFILES)
        if fp is None:
            error("Fika profile not found.")
            return

        shutil.copy2(fp, USER_PROFILES)
        info("Local profile overwritten with downloaded profile.")

    def download_profile(self):
        server = self.launcher_config.remote["Server"]["Url"]
        creds = self.launcher_config.remote["Server"]["AutoLoginCreds"]
        status, session_id = self.http.login(server, creds)
        if status is None:
            return
        elif status != 200:
            error(f"Unexpected response:\n{status} {session_id}")
            return

        url = urljoin(self.launcher_config.remote["Server"]["Url"], HTTP.DOWNLOAD_ENDPOINT)
        status, profile = self.http.request(url, session_id=session_id)
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

    def upload_profile(self):
        _, profile = self._find_profile(USER_PROFILES)
        if profile is None:
            error("Failed to find local profile.")
            return

        url = urljoin(self.launcher_config.remote["Server"]["Url"], HTTP.UPLOAD_ENDPOINT)
        status, data = self.http.request(url, data=profile)
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

    def update_server_label(self):
        if self.launcher_config.is_local:
            self.server_label["text"] = "local"
            self.server_label["foreground"] = "green"
        else:
            self.server_label["text"] = "remote"
            self.server_label["foreground"] = "blue"

    def change_launcher_config(self):
        self.launcher_config.switch()
        self.update_server_label()


def error(message: str):
    messagebox.showerror(TITLE, message)


def info(message: str):
    messagebox.showinfo(TITLE, message)


def load_json(fp: Path):
    return json.loads(fp.read_text('utf-8'))


if __name__ == '__main__':
    if not GAME_EXE.exists():
        error('EscapeFromTarkov.exe not found.')
        sys.exit()

    FIKA_PROFILES.mkdir(parents=True, exist_ok=True)
    USER_PROFILES.mkdir(parents=True, exist_ok=True)

    MainWindow().mainloop()
