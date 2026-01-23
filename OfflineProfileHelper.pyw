#!/usr/bin/env pythonw3
import json
import shutil
import ssl
import sys
import tkinter as tk
import zlib
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Self, Sequence, TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


TITLE = "OPH"

if getattr(sys, "frozen", False):  # PyInstaller-specific(?) check
    GAME_DIR = Path(sys.executable).parent
else:                              # not packed, just the script being run
    GAME_DIR = Path(__file__).parent
GAME_EXE = GAME_DIR / "EscapeFromTarkov.exe"

PROFILE_DATA_DIR = GAME_DIR / "SPT" / "user" / "profileData"
USER_PROFILES = GAME_DIR / "SPT" / "user" / "profiles"
FIKA_PROFILES = GAME_DIR / "SPT" / "user" / "fika"


class AutoLoginCreds(TypedDict):
    Username: str

class ServerConfig(TypedDict):
    Name: str
    Url: str
    AutoLoginCreds: AutoLoginCreds

class LauncherConfig(TypedDict):
    Server: ServerConfig


class ConfigServer(TypedDict):
    Name: str
    Url: str
    FikaApiKey: str


class ConfigFile:
    filepath: Path
    data: Any

    def load(self) -> Self:
        if not self.filepath.exists():
            msg = f'{self.filepath} does not exist.'
            raise FileNotFoundError(msg)

        self.data = json.loads(self.filepath.read_text())
        return self

    def save(self):
        self.filepath.write_text(json.dumps(self.data, indent=2))

class LauncherConfigFile(ConfigFile):
    filepath = GAME_DIR / "SPT" / "user" / "launcher" / "config.json"
    data: LauncherConfig

    def set_server(self, server: ConfigServer):
        self.data['Server']['Name'] = server['Name']
        self.data['Server']['Url'] = server['Url']
        self.save()

    @property
    def is_local(self) -> bool:
        return '127.0.0.1' in self.data['Server']['Url']

    @property
    def username(self) -> str:
        return self.data["Server"]["AutoLoginCreds"]["Username"]


class AppConfigFile(ConfigFile):
    filepath = GAME_DIR / 'OfflineProfileHelper.json'
    data: list[ConfigServer]
    current_index: int = 0

    def load(self) -> Self:
        try:
            super().load()
        except FileNotFoundError:
            self.data = []

        return self

    def ensure_default_servers(self, launcher_config: LauncherConfig):
        if len(self.data) == 0:
            local = ConfigServer(Name="local", Url="https://127.0.0.1:6969", FikaApiKey="")
            self.data.append(local)

        current_url = launcher_config["Server"]["Url"]
        for index, server in enumerate(self.data):
            if server["Url"] == current_url:
                self.current_index = index
                return
        else:
            current = ConfigServer(Name="remote", Url=current_url, FikaApiKey="")
            self.data.append(current)
            self.current_index = index + 1

    @property
    def current_server(self) -> ConfigServer:
        return self.data[self.current_index]

    def add_server(self, server: ConfigServer):
        self.data.append(server)
        self.current_index = len(self.data) - 1
        self.save()

    def remove_server(self):
        self.data.pop(self.current_index)
        if self.current_index == len(self.data):
            self.current_index -= 1
        self.save()

    def update_server(self, server: ConfigServer):
        self.data[self.current_index] = server
        self.save()


class HTTP:
    LOGIN_ENDPOINT = "/launcher/profile/login"
    DOWNLOAD_ENDPOINT = "/fika/profile/download"
    UPLOAD_ENDPOINT = "/fika/api/uploadprofile"

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

    def _request(self, url: str, *,  # noqa: C901 complexity
                 data: dict | None = None,
                 session_id: str | None = None,
                 fika_api_key: str | None = None,
                 compress: bool = True,
                 expected_codes: Sequence[int] = (200,)) \
                 -> tuple[int, str] | tuple[None, None]:
        req = Request(url)  # noqa: S310
        if data is not None:
            if compress:
                req.data = self.compress_json(data)
            else:
                req.data = json.dumps(data).encode()
        if session_id:
            req.add_header("Cookie", f"PHPSESSID={session_id}")
        if fika_api_key:
            req.add_header("Authorization", f"Bearer {fika_api_key}")

        try:
            resp = urlopen(req, timeout=3, context=self._ssl)  # noqa: S310
        except HTTPError as e:
            if e.status in expected_codes:
                if compress:
                    return e.status, zlib.decompress(e.fp.read()).decode()
                else:
                    return e.status, e.fp.read().decode()
            error(f"Server returned unexpected error {e.status}.")
        except URLError:
            error("Failed to connect.\nIs the server running?")
        except TimeoutError:
            error("Request timed out.")
        except Exception as e:
            error(f"Unknown error:\n{e}")
        else:
            if compress:
                return 200, zlib.decompress(resp.read()).decode()
            else:
                return 200, resp.read().decode()

        return None, None

    def login(self, server_url: str, credentials: AutoLoginCreds) \
            -> tuple[int, str] | tuple[None, None]:
        if credentials is None:
            error('Cannot find profile name, launcher is not logged in.')
            return None, None

        creds = {
            'username': credentials['Username']
        }

        url = urljoin(server_url, self.LOGIN_ENDPOINT)
        _, data = self._request(url, data=creds)

        if data is not None:
            return 200, data

        return None, None

    def request(self, url: str, *,
                data: dict | None = None,
                session_id: str | None = None,
                fika_api_key: str | None = None,
                compress: bool = True,
                is_spt: bool = True,
                expected_codes: Sequence[int] = (200,)) \
                -> tuple[int, dict] | tuple[int, str] | tuple[None, None]:
        code, resp = self._request(url, data=data,
                                   session_id=session_id,
                                   fika_api_key=fika_api_key,
                                   compress=compress,
                                   expected_codes=expected_codes)
        if code is None or resp is None:
            return None, None

        if not is_spt:
            return code, resp

        data = json.loads(resp)
        err = data.get('err')
        if err:
            return err, data.get('errmsg')

        return code, data


class MainWindow(tk.Tk):
    http: HTTP
    launcher_config: LauncherConfigFile
    app_config: AppConfigFile

    upload_button: ttk.Button
    delete_button: ttk.Button
    server_list: ttk.Combobox

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.http = HTTP()
        self.launcher_config = LauncherConfigFile().load()
        self.app_config = AppConfigFile().load()
        self.app_config.ensure_default_servers(self.launcher_config.data)

        self.resizable(width=False, height=False)
        self.title(TITLE)

        outer_frame = ttk.Frame(self, padding=2)
        outer_frame.pack()

        ttk.Button(outer_frame, text="Download Profile", command=self.download_profile).grid(column=0, row=0, sticky=tk.EW)
        ttk.Button(outer_frame, text="Overwrite Profile", command=self.overwrite_profile).grid(column=0, row=1, sticky=tk.EW)
        self.upload_button = ttk.Button(outer_frame, text="Upload Profile", command=self.upload_profile)
        self.upload_button.grid(column=0, row=2, sticky=tk.EW)
        self.update_upload_button()

        ttk.Label(outer_frame, text="Current Server").grid(column=1, row=0)
        self.server_list = ttk.Combobox(outer_frame, state="readonly", width=15)
        self.server_list.bind("<<ComboboxSelected>>", self.server_selected)
        self.server_list.grid(column=1, row=1, sticky=tk.EW)
        self.update_server_list()
        server_btn_frame = ttk.Frame(outer_frame)
        server_btn_frame.grid(column=1, row=2, sticky=tk.EW)
        ttk.Button(server_btn_frame, text="+", command=self.add_server, width=2).pack(side="left")
        self.delete_button = ttk.Button(server_btn_frame, text="-", command=self.delete_server, width=2)
        self.delete_button.pack(side="left")
        self.update_delete_button()
        ttk.Button(server_btn_frame, text="Edit", command=self.edit_server).pack(side="right")

    def _get_local_profile(self) -> dict | None:
        current_username = self.launcher_config.username
        if not USER_PROFILES.exists():
            return None

        for fp in USER_PROFILES.iterdir():
            if not fp.is_file():
                continue

            try:
                profile = load_json(fp)
            except Exception:  # noqa: S112
                continue
            if profile['info']['username'] == current_username:
                return profile

        return None

    def _find_fika_profile(self) -> Path | None:
        current_username = self.launcher_config.username
        if not FIKA_PROFILES.exists():
            return None

        for fp in FIKA_PROFILES.iterdir():
            if not fp.is_dir():
                continue

            profile_fp = fp / f'{fp.name}.json'

            try:
                profile = load_json(profile_fp)
            except Exception:  # noqa: S112
                continue
            if profile['info']['username'] == current_username:
                return profile_fp

        return None

    def overwrite_profile(self):
        profile = self._find_fika_profile()
        if profile is None:
            error("Fika profile not found.")
            return

        shutil.copy2(profile, USER_PROFILES)

        profile_dir = profile.parent
        profile_id = profile_dir.name
        profile_data_dir = PROFILE_DATA_DIR / profile_id
        profile_data_dir.mkdir(parents=True, exist_ok=True)
        for fp in profile_data_dir.iterdir():
            if fp == profile:
                continue
            shutil.copy2(fp, profile_data_dir)

        info("Local profile overwritten with downloaded profile.")

    def download_profile(self):
        server = self.app_config.current_server["Url"]
        creds = self.launcher_config.data["Server"]["AutoLoginCreds"]
        status, session_id = self.http.login(server, creds)
        if status is None or session_id is None:
            return
        elif session_id == 'FAILED':
            error(f'Profile with name "{creds['Username']}" does not exist in server.')
            return
        elif status != 200:
            error(f"Unexpected response:\n{status} {session_id}")
            return

        url = urljoin(self.app_config.current_server["Url"], HTTP.DOWNLOAD_ENDPOINT)
        status, response = self.http.request(url, session_id=session_id)
        if status is None or response is None:
            return
        elif status == 404:
            error("Failed to download profile.\nIs Fika installed on the server?")
            return
        elif status != 200:
            error(f"Unexpected response:\n{status} {response}")
            return

        profile: dict[str, Any] = response['profile']  # ty:ignore[invalid-argument-type]
        mod_data: dict[str, str] = response.get('modData', {})  # ty:ignore[invalid-argument-type, possibly-missing-attribute]

        profile_dir = FIKA_PROFILES / session_id
        profile_dir.mkdir(parents=True, exist_ok=True)
        fp = profile_dir / f'{session_id}.json'
        fp.write_text(json.dumps(profile, indent='\t'))

        for mod, data in mod_data.items():
            fp = profile_dir / f'{mod}.json'
            fp.write_text(data)

        info("Profile downloaded successfully.")

    def upload_profile(self):
        profile = self._get_local_profile()
        if profile is None:
            error("Failed to find local profile.")
            return

        url = urljoin(self.app_config.current_server["Url"], HTTP.UPLOAD_ENDPOINT)
        status, data = self.http.request(url, data=profile,
                                         fika_api_key=self.app_config.current_server["FikaApiKey"],
                                         compress=False, is_spt=False,
                                         expected_codes=(200, 400, 401, 423, 500))
        if status is None:
            return

        message = str(data)
        if status == 200:
            info(message)
        else:
            error(message)

    def update_upload_button(self):
        server = self.app_config.current_server
        if server['FikaApiKey']:
            self.upload_button.configure(state='normal')
        else:
            self.upload_button.configure(state='disabled')

    def server_selected(self, _):
        if self.server_list.current() == self.app_config.current_index:
            return

        self.app_config.current_index = self.server_list.current()
        self.launcher_config.set_server(self.app_config.current_server)

        self.update_upload_button()

    def update_server_list(self):
        self.server_list.configure(values=[server["Name"] for server in self.app_config.data])
        self.server_list.current(self.app_config.current_index)

    def add_server(self):
        window = EditServerWindow(self)
        self.wait_window(window)

        if window.server is not None:
            self.app_config.add_server(window.server)
            self.update_server_list()
            self.update_upload_button()
            self.update_delete_button()

    def delete_server(self):
        server = self.app_config.current_server
        name = server["Name"]
        url = server["Url"]
        confirm = messagebox.askyesno("Confirmation", f'Really delete server?\nName: {name}\nURL: {url}')

        if confirm:
            self.app_config.remove_server()
            self.update_server_list()
            self.update_upload_button()
            self.update_delete_button()

    def update_delete_button(self):
        if len(self.app_config.data) > 1:
            self.delete_button.configure(state='normal')
        else:
            self.delete_button.configure(state='disabled')

    def edit_server(self):
        window = EditServerWindow.prefill(self, self.app_config.current_server)
        self.wait_window(window)

        if window.server is not None:
            self.app_config.update_server(window.server)
            self.update_server_list()
            self.update_upload_button()


class EditServerWindow(tk.Toplevel):
    server: ConfigServer | None

    __name: tk.StringVar
    __url: tk.StringVar
    __fika_api_key: tk.StringVar

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.resizable(width=True, height=False)
        self.title("New Server")

        self.__name = tk.StringVar(self)
        self.__url = tk.StringVar(self)
        self.__fika_api_key = tk.StringVar(self)

        frame = ttk.Frame(self, padding=2)
        frame.pack(expand=True, fill=tk.BOTH)

        nframe = ttk.LabelFrame(frame, text="Name")
        nframe.pack(fill=tk.X)
        tk.Entry(nframe, textvariable=self.__name).pack(fill=tk.X)
        uframe = ttk.LabelFrame(frame, text="URL")
        uframe.pack(fill=tk.X)
        tk.Entry(uframe, textvariable=self.__url).pack(fill=tk.X)
        aframe = ttk.LabelFrame(frame, text="Fika API Key")
        aframe.pack(fill=tk.X)
        tk.Entry(aframe, textvariable=self.__fika_api_key).pack(fill=tk.X)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(anchor=tk.SE)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Ok",command=self.ok).pack(side=tk.RIGHT)

        self.grab_set()

    def destroy(self):
        super().destroy()
        self.grab_release()

    @classmethod
    def prefill(cls, master: tk.Misc, server: ConfigServer) -> Self:
        self = cls(master)

        self.title("Edit Server")
        self.__name.set(server["Name"])
        self.__url.set(server["Url"])
        self.__fika_api_key.set(server["FikaApiKey"])

        return self

    def ok(self):
        self.server = ConfigServer(Name=self.__name.get(), Url=self.__url.get(), FikaApiKey=self.__fika_api_key.get())
        self.destroy()


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
