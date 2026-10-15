# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The editor's local server: the Scenario Editor, served from this computer, with a
button that runs quicksat and writes the viewer.

    python -m quicksat.editor serve sample/power/data sample/power/output

`serve` starts a server that only this computer can reach, and opens the editor
in the browser. The page is written from the folder at each load, as
`write_editor` writes it, so a reload shows the files as they are on disk, with
quicksat's full check.

**Create the viewer**, on the page, sends the page's files to the server.
`run_files` writes them into a temporary folder, reads them with quicksat's
loaders, runs them, and writes the viewer into the output folder, as
`python -m quicksat.scenario` and `python -m quicksat.power` do. The run uses
the files as they are on the page, saved or not. It does not change the files
in the input folder. The server also serves the output folder, so the page can
open the viewer it wrote.

The server is for one user, on one computer:

- It listens on 127.0.0.1, which other computers cannot reach.
- Each start makes a random key, which every address must end with, as in
  `http://localhost:8780/quicksat/editor?key=k3Xq9vTzR2mA`. A page from another
  site does not know it, so it can neither read the folder's files nor ask for a
  run.
- It refuses a request whose `Host` is not its own address. This stops a site
  that points its own name at 127.0.0.1 from reaching it.

"""

import base64
import binascii
import json
import posixpath
import secrets
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from urllib.parse import parse_qs, unquote, urlsplit

from quicksat.editor.editor import _check, editor_data, editor_page
from quicksat.power import CONSUMPTION_FILE, POWER_FILE
from quicksat.power.__main__ import run_folder, summary
from quicksat.power.config import PowerSystem
from quicksat.power.consumption import PowerConsumption
from quicksat.power.viewer import PAGE_FILE as POWER_PAGE
from quicksat.power.viewer import write_power_viewer
from quicksat.scenario import SCENARIO_FILE
from quicksat.scenario.config import Scenario
from quicksat.scenario.run import run_scenario
from quicksat.scenario.viewer import PAGE_FILE as SCENARIO_PAGE
from quicksat.scenario.viewer import write_scenario_viewer

HOST = "127.0.0.1"
"""The address the server listens on: this computer only."""

PORT = 8780
"""The port the server tries first. If another program has it, the server tries
the next ones, then any free port."""

PORTS_TRIED = 20
"""How many ports from `PORT` on the server tries, before any free one."""

PREFIX = "/quicksat/"
"""The start of every address the server answers: `editor`, `status`, `run` and
`viewer/` follow it."""

MAX_BODY = 200 * 1024 * 1024
"""The largest run request the server reads, in bytes. The 3D model is the
largest file, in base64."""

VIEWER_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".ecsv": "text/plain; charset=utf-8",
}
"""The files of the output folder that the server serves, by their suffix."""

_ROLES = {
    "scenario": Scenario.from_yaml_file,
    "power": PowerSystem.from_yaml_file,
    "consumption": PowerConsumption.from_csv,
}
"""The files that quicksat reads, by their kind, with their loaders."""


def _label(path: Path) -> str:
    """A folder as the user gave it when relative, and its name otherwise."""
    return path.as_posix() if not path.is_absolute() else path.name


def _argument(path: Path) -> str:
    """A path as a command line takes it: in double quotes if it has a space."""
    return f'"{path}"' if " " in str(path) else str(path)


def _relative(name: str) -> str | None:
    """
    A file's name as a relative path in `/` form, or None if it is absolute.

    Parameters
    ----------
    name : str
        The name as the scenario gives it, with `/` or `\\`

    Returns
    -------
    path : str or None
        The name, normalised, such as `../models/sat.glb`
    """
    name = name.replace("\\", "/")
    if name.startswith("/") or PureWindowsPath(name).drive:
        return None
    return posixpath.normpath(name)


def _write_inputs(root: Path, files: list[dict]) -> tuple[Path, dict]:
    """
    Write the page's files into a folder, where the scenario will find them.

    The scenario names its 3D model and orbit file by a path from its own folder,
    which may start with `..`. So the scenario goes deep enough inside `root` for
    each such path to stay inside it too. A file named by an absolute path is not
    written: quicksat reads it from where it is.

    Parameters
    ----------
    root : Path
        An empty folder
    files : list of dict
        The page's files, each with `kind`, `name`, and `text` or `base64`

    Returns
    -------
    base : Path
        The folder that holds the scenario file
    names : dict
        The names of the files that quicksat reads, by kind

    Raises
    ------
    ValueError
        If a file has no name, or the scenario, the power system or the
        consumption is not a plain file name
    """
    paths = {}
    for file in files:
        name = file.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                f"The page sent a {file.get('kind', '')} file with no name."
            )
        paths[id(file)] = _relative(name)
    # a normalised path has its `..` at the start only
    depth = max((p.split("/").count("..") for p in paths.values() if p), default=0)
    base = root.joinpath(*[f"up{i}" for i in range(depth)], "folder")
    base.mkdir(parents=True)
    names = {}
    for file in files:
        path = paths[id(file)]
        if file.get("kind") in _ROLES:
            if path is None or "/" in path or path in (".", ".."):
                raise ValueError(
                    f"Cannot run a file named {file['name']}: give it a plain file name."
                )
            names[file["kind"]] = path
        if path is None:
            continue
        target = base / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if "base64" in file:
            target.write_bytes(base64.b64decode(file["base64"], validate=True))
        else:
            target.write_text(str(file.get("text", "")), encoding="utf-8")
    return base, names


def run_files(files: list[dict], output: str | Path) -> dict:
    """
    Run the editor's files, and write the viewer.

    The files go in a temporary folder, which is deleted after the run. quicksat's
    loaders read the scenario and, if there are any, the power system and the
    consumption. If they all read, the run goes ahead: the power budget when
    both power files are there, and the scenario alone otherwise. The viewer
    goes in `output`, as `python -m quicksat.scenario` or `python -m quicksat.power`
    would write it.

    Parameters
    ----------
    files : list of dict
        The page's files, each with `kind`: `scenario`, `model`, `orbit`,
        `power` or `consumption`. `name`: the name the scenario gives it, or the
        file's own name. `text`, or `base64` for the 3D model.
    output : str | Path
        The folder to write the viewer in. It is made if it does not exist.

    Returns
    -------
    result : dict
        `ok`, and `checks`, what quicksat's loaders said of each file, as the
        editor's page holds them. When `ok`: `page`, the viewer's page in
        `output`, `report`, the results as the command prints them, and
        `seconds`, the time taken. Otherwise `error`, the reason, with no
        temporary path in it.
    """
    start = time.perf_counter()
    if not any(file.get("kind") == "scenario" for file in files):
        return {"ok": False, "error": "The page holds no scenario file.", "checks": []}
    with tempfile.TemporaryDirectory(prefix="quicksat_run_") as tmp:
        root = Path(tmp)

        def clean(text: str) -> str:
            return (
                text.replace(f"{base}/", "")
                .replace(str(base), "the folder")
                .replace(str(root), "")
            )

        try:
            base, names = _write_inputs(root, files)
        except (ValueError, binascii.Error) as error:
            return {"ok": False, "error": str(error), "checks": []}
        checks = []
        for kind, loader in _ROLES.items():
            if kind in names:
                path = base / names[kind]
                check = _check(names[kind], lambda read=loader, path=path: read(path))
                checks.append({**check, "message": clean(check["message"])})
        refused = [check for check in checks if not check["ok"]]
        if refused:
            listed = ", ".join(check["file"] for check in refused)
            return {
                "ok": False,
                "error": f"quicksat cannot read {listed}, so it did not run the files.",
                "checks": checks,
            }
        try:
            if "power" in names and "consumption" in names:
                budget = run_folder(
                    base, names["scenario"], names["power"], names["consumption"]
                )
                report = summary(budget)
                page = write_power_viewer(budget, output)
            else:
                run = run_scenario(Scenario.from_yaml_file(base / names["scenario"]))
                report = run.report
                page = write_scenario_viewer(run, output)
        except (OSError, ValueError) as error:
            return {"ok": False, "error": clean(str(error)), "checks": checks}
    return {
        "ok": True,
        "page": page.name,
        "report": report,
        "checks": checks,
        "seconds": round(time.perf_counter() - start, 1),
    }


class EditorServer(ThreadingHTTPServer):
    """
    The Scenario Editor for one folder, served on this computer, with its runs.

    Parameters
    ----------
    folder : str | Path
        The folder that holds the input files. It must hold the scenario file.
    output : str | Path
        The folder to write the viewer in
    port : int, optional
        The port to listen on, and 0 for any free one. By default, `PORT` or the
        next free one after it.
    scenario_file, power_file, consumption_file : str, optional
        The files' names, if not the usual ones. See `editor_data`.
    """

    daemon_threads = True
    # on Windows, this would let a second server take a port that one already has
    allow_reuse_address = sys.platform != "win32"

    def __init__(
        self,
        folder: str | Path,
        output: str | Path,
        port: int | None = None,
        scenario_file: str = SCENARIO_FILE,
        power_file: str = POWER_FILE,
        consumption_file: str = CONSUMPTION_FILE,
    ):
        self.folder = Path(folder)
        self.output = Path(output)
        self.names = (scenario_file, power_file, consumption_file)
        if not (self.folder / scenario_file).is_file():
            raise FileNotFoundError(f"no scenario file: {self.folder / scenario_file}")
        # 12 characters, 72 bits: a guess costs a request to this computer
        self.key = secrets.token_urlsafe(9)
        self.run_lock = threading.Lock()
        ports = [port] if port is not None else [*range(PORT, PORT + PORTS_TRIED), 0]
        for number in ports:
            try:
                super().__init__((HOST, number), _Handler)
                break
            except OSError:
                if number == ports[-1]:
                    raise

    @property
    def url(self) -> str:
        """The editor's address, with the key. Only this computer can open it."""
        return f"http://localhost:{self.server_port}{PREFIX}editor?key={self.key}"

    def viewer_pages(self) -> list[str]:
        """The viewer pages in the output folder now."""
        return [
            name
            for name in (SCENARIO_PAGE, POWER_PAGE)
            if (self.output / name).is_file()
        ]

    def page(self) -> str:
        """The editor's page, written from the folder as it is now."""
        data = editor_data(self.folder, *self.names)
        data["server"] = {
            "base": PREFIX,
            "key": self.key,
            "folder": _label(self.folder),
            "output": _label(self.output),
            # the paths as the user gave them: this page stays on this computer
            "command": f"python -m quicksat.editor serve {_argument(self.folder)} "
            f"{_argument(self.output)}",
            "viewers": self.viewer_pages(),
        }
        return editor_page(data)


_STRANGER = """<!doctype html><meta charset="utf-8"><title>quicksat</title>
<p>This is the quicksat editor's server. Open the address that the server printed
when it started. It ends with a key, <code>?key=</code>, that this address lacks.</p>"""


class _Handler(BaseHTTPRequestHandler):
    """Answers the page: the editor, its status, its runs and the viewer's files."""

    server: EditorServer

    def log_message(self, format, *args):  # noqa: A002
        """Print nothing for each request: the runs print their own lines."""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # the address ends with the key, so it goes to no other site
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: dict) -> None:
        self._send(status, json.dumps(value).encode("utf-8"), "application/json")

    def _own(self, header: str, prefix: str = "") -> bool:
        """Whether a header names this server: 127.0.0.1 or localhost, on its port."""
        port = self.server.server_port
        value = self.headers.get(header, "")
        return value in (f"{prefix}{HOST}:{port}", f"{prefix}localhost:{port}")

    def _route(self) -> str | None:
        """The address after `PREFIX`, or None if the key is wrong or missing."""
        address = urlsplit(self.path)
        path = unquote(address.path)
        key = parse_qs(address.query).get("key", [""])[0]
        if not path.startswith(PREFIX) or not secrets.compare_digest(
            key, self.server.key
        ):
            return None
        return path.removeprefix(PREFIX)

    def do_GET(self):  # noqa: N802
        """The page, its status, or a file of the viewer."""
        if not self._own("Host"):
            self._send(
                HTTPStatus.FORBIDDEN, b"Not this server's address.", "text/plain"
            )
            return
        route = self._route()
        if route is None:
            self._send(
                HTTPStatus.NOT_FOUND,
                _STRANGER.encode("utf-8"),
                "text/html; charset=utf-8",
            )
        elif route == "editor":
            try:
                page = self.server.page()
            except (OSError, ValueError) as error:
                self._send(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    str(error).encode("utf-8"),
                    "text/plain; charset=utf-8",
                )
                return
            self._send(HTTPStatus.OK, page.encode("utf-8"), "text/html; charset=utf-8")
        elif route == "status":
            self._json(
                HTTPStatus.OK, {"ok": True, "viewers": self.server.viewer_pages()}
            )
        elif route.startswith("viewer/"):
            self._viewer_file(route.removeprefix("viewer/"))
        else:
            self._send(HTTPStatus.NOT_FOUND, b"Not found.", "text/plain")

    def _viewer_file(self, name: str) -> None:
        """A file of the output folder: a page, a script or an attitude file."""
        path = self.server.output / name
        kind = VIEWER_TYPES.get(Path(name).suffix)
        if (
            "/" in name
            or "\\" in name
            or name.startswith(".")
            or not kind
            or not path.is_file()
        ):
            self._send(HTTPStatus.NOT_FOUND, b"Not found.", "text/plain")
            return
        body = path.read_bytes()
        if path.suffix == ".html":
            # the viewer loads its data by name, so the names carry the key too
            for data in (b"scenario.js", b"power.js"):
                key = f"?key={self.server.key}".encode("ascii")
                body = body.replace(
                    b'src="' + data + b'"', b'src="' + data + key + b'"'
                )
        self._send(HTTPStatus.OK, body, kind)

    def do_POST(self):  # noqa: N802
        """A run: the page's files in, the viewer out."""
        if not self._own("Host") or (
            "Origin" in self.headers and not self._own("Origin", "http://")
        ):
            self._send(HTTPStatus.FORBIDDEN, b"Not this server's page.", "text/plain")
            return
        if self._route() != "run":
            self._send(HTTPStatus.NOT_FOUND, b"Not found.", "text/plain")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if (
            not self.headers.get("Content-Type", "").startswith("application/json")
            or length > MAX_BODY
        ):
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "The request is not a run.", "checks": []},
            )
            return
        try:
            files = json.loads(self.rfile.read(length))["files"]
        except (ValueError, KeyError, TypeError):
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "The request is not a run.", "checks": []},
            )
            return
        if not self.server.run_lock.acquire(blocking=False):
            self._json(
                HTTPStatus.CONFLICT,
                {
                    "ok": False,
                    "error": "A run is going already. Wait for it to end.",
                    "checks": [],
                },
            )
            return
        try:
            print(
                f"{time.strftime('%H:%M:%S')}  running the page's files ...", flush=True
            )
            result = run_files(files, self.server.output)
        except Exception as error:  # a fault in quicksat: show it, and keep serving
            traceback.print_exc()
            result = {
                "ok": False,
                "error": f"quicksat failed: {type(error).__name__}: {error}. The server's window shows the details.",
                "checks": [],
            }
        finally:
            self.server.run_lock.release()
        if result["ok"]:
            print(
                f"{time.strftime('%H:%M:%S')}  wrote {self.server.output / result['page']} in {result['seconds']} s",
                flush=True,
            )
        else:
            print(
                f"{time.strftime('%H:%M:%S')}  no viewer: {result['error']}", flush=True
            )
        self._json(HTTPStatus.OK, result)


def serve(server: EditorServer, open_browser: bool = True) -> None:
    """
    Serve the editor until the user stops it with Ctrl+C.

    Parameters
    ----------
    server : EditorServer
        The server, made and listening
    open_browser : bool, optional
        Whether to open the editor in the browser
    """
    print(
        f"The Scenario Editor for {_label(server.folder)} is at\n\n    {server.url}\n"
    )
    print(f"Create the viewer on the page, and it goes in {_label(server.output)}.")
    print(
        "Keep this window open while you work. Press Ctrl+C to stop the server.",
        flush=True,
    )
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nThe server has stopped.")
    finally:
        server.server_close()
