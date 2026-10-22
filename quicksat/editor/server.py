# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The editor's local server: an editor page, served from this computer, which runs
quicksat on the page's files.

    python -m quicksat.editor serve sample/power/data sample/power/output
    python -m quicksat.editor serve sample/sizing/data

A folder with a scenario file gets the Scenario Editor, with a button that runs
quicksat and writes the viewer into the output folder. A folder of sizing files
gets the Sizing Editor, whose Budgets tab shows every budget worked out by
quicksat, and needs no output folder.

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

**Generate scenario**, in the Activity Designer, sends the files in the same way.
`design_files` runs the scenario alone, once or with repeats, and writes
nothing. The server keeps the viewer page with the run's data inside, and sends
it to the designer's frame. **Save into the folder** sends the files that
changed, and `save_files` writes them into the input folder. It refuses a file
that changed on disk since the page was written.

**The budgets**, on the Sizing Editor's Budgets tab, follow the page's files.
After each change, the page sends them, and `budget_files` works out every
budget in a temporary folder, and writes nothing.

**Stop the server**, in the page's header, stops the server, as Ctrl+C does in
its window. A server started from a shortcut has no window to press Ctrl+C in.
The server also stops by itself after 48 h with no editor page open, as
`IDLE_S` says.

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
import hashlib
import json
import os
import posixpath
import secrets
import shutil
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from urllib.parse import parse_qs, unquote, urlsplit

from quicksat.editor.budgets import budget_results
from quicksat.editor.editor import _check, editor_data, editor_page
from quicksat.editor.sizing import NAMES as SIZING_NAMES
from quicksat.editor.sizing import sizing_data, sizing_page
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
from quicksat.scenario.viewer import (
    activity_rows,
    designer_page,
    scenario_data,
    write_scenario_viewer,
)

HOST = "127.0.0.1"
"""The address the server listens on: this computer only."""

PORT = 8780
"""The port the server tries first. If another program has it, the server tries
the next ones, then any free port."""

PORTS_TRIED = 20
"""How many ports from `PORT` on the server tries, before any free one."""

PREFIX = "/quicksat/"
"""The start of every address the server answers: `editor`, `status`, `run`,
`design`, `designer`, `save`, `budgets`, `stop` and `viewer/` follow it."""

IDLE_S = 48 * 3600
"""How long the server runs with no request from a page before it stops by
itself, in seconds: 48 h. An editor page asks every few seconds while it is in
view, and every 10 min while it is not."""

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

_DESIGN_ROLES = {
    "scenario": lambda path: Scenario.from_yaml_file(path, designer=True),
}
"""The files that the Activity Designer reads, with their loaders. It runs the
scenario alone, so it leaves the power files out."""


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

    The scenario names its 3D model, its orbit file and its satellite targets'
    files by a path from its own folder, which may start with `..`. So the scenario goes deep enough inside `root` for
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


def _run_inputs(
    files: list[dict], roles: dict, work: Callable[[Path, dict], dict]
) -> dict:
    """
    Write the page's files into a temporary folder, check them, and run them.

    The folder is deleted after the run. quicksat's loaders read each file that
    `roles` names. If they all read, `work` runs on the folder.

    Parameters
    ----------
    files : list of dict
        The page's files, as `_write_inputs` takes them
    roles : dict
        The loader of each kind of file to check, by the kind
    work : callable
        Runs the files, given the folder of the scenario and the names of the
        files by kind. It gives the result's own fields.

    Returns
    -------
    result : dict
        `ok`, and `checks`, what the loaders said of each file. When `ok`, the
        fields from `work`, and `seconds`, the time taken. Otherwise `error`,
        the reason, with no temporary path in it.
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
        for kind, loader in roles.items():
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
            result = work(base, names)
        except (OSError, ValueError) as error:
            return {"ok": False, "error": clean(str(error)), "checks": checks}
    return {
        "ok": True,
        **result,
        "checks": checks,
        "seconds": round(time.perf_counter() - start, 1),
    }


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
        `power`, `consumption`, or `target:` and the file's name for a
        satellite target's file. `name`: the name the scenario gives it, or the
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

    def work(base: Path, names: dict) -> dict:
        if "power" in names and "consumption" in names:
            budget = run_folder(
                base, names["scenario"], names["power"], names["consumption"]
            )
            return {
                "page": write_power_viewer(budget, output).name,
                "report": summary(budget),
            }
        run = run_scenario(Scenario.from_yaml_file(base / names["scenario"]))
        return {"page": write_scenario_viewer(run, output).name, "report": run.report}

    return _run_inputs(files, _ROLES, work)


def design_files(files: list[dict], repeat: bool) -> dict:
    """
    Run the editor's scenario for the Activity Designer, and write nothing.

    The files go in a temporary folder, as for `run_files`. The scenario is read
    as the designer reads it, so its list of activities may be empty. The power
    files are left out, and the scenario runs alone.

    Parameters
    ----------
    files : list of dict
        The page's files, as `run_files` takes them
    repeat : bool
        Whether to repeat the list of activities until the run ends, or run it
        once

    Returns
    -------
    result : dict
        `ok`, `checks` and `seconds`, or `error`, as from `run_files`. When `ok`:
        `data`, the viewer's data from `scenario_data` for the designer, and
        `id`, its id. `rows`, the results of each activity from
        `activity_rows`, and `warnings`, the run's warnings. `duration_s`, the
        run's length, `period_s`, the orbit's period, and `pass_s`, the length
        of one pass of the list, or None. `max_rate_deg_s` and
        `max_acceleration_deg_s2`, the slew block's limits, or None.
    """
    files = [file for file in files if file.get("kind") not in ("power", "consumption")]

    def work(base: Path, names: dict) -> dict:
        path = base / names["scenario"]
        run = run_scenario(Scenario.from_yaml_file(path, designer=True), repeat)
        data = scenario_data(run, designer=True)
        attitude = data["attitude"]
        return {
            "data": data,
            "id": data["id"],
            "rows": activity_rows(run),
            "warnings": data["warnings"],
            "duration_s": data["grid"]["t_s"][-1],
            "period_s": data["orbit"]["period_s"],
            "pass_s": data["designer"]["pass_s"],
            "max_rate_deg_s": attitude["max_rate_deg_s"],
            "max_acceleration_deg_s2": attitude["max_acceleration_deg_s2"],
        }

    return _run_inputs(files, _DESIGN_ROLES, work)


def budget_files(files: list[dict]) -> dict:
    """
    Work out the sizing budgets from the Sizing Editor's files, and write nothing.

    The files go in a temporary folder, under their kinds' usual names, which is
    deleted afterwards. A file of a kind that the sizing folder does not have is
    left out.

    Parameters
    ----------
    files : list of dict
        The page's files, each with `kind`, such as `mission` or `equipment`, and
        `text`

    Returns
    -------
    result : dict
        `ok`, `results`, from `budget_results`, with no temporary path in them,
        and `seconds`, the time taken. Otherwise `error`, the reason.
    """
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="quicksat_budgets_") as tmp:
        root = Path(tmp)
        for file in files:
            name = SIZING_NAMES.get(str(file.get("kind")))
            text = file.get("text")
            if name is None:
                continue
            if not isinstance(text, str):
                return {"ok": False, "error": f"The page sent {name} with no text."}
            (root / name).write_text(text, encoding="utf-8")
        results = budget_results(root)
    # the messages may name the temporary folder
    text = json.dumps(results).replace(f"{root}{os.sep}", "").replace(str(root), "")
    return {
        "ok": True,
        "results": json.loads(text),
        "seconds": round(time.perf_counter() - start, 2),
    }


def file_hash(path: Path) -> str:
    """
    The SHA-256 of a file's bytes, as the page and the server compare it.

    Parameters
    ----------
    path : Path
        The file

    Returns
    -------
    sha256 : str
        64 hex digits
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_files(folder: str | Path, files: list[dict]) -> dict:
    """
    Write the page's files into the input folder, unless one changed on disk.

    Each file names the SHA-256 of the file as the page last read or saved it. A
    file whose bytes on disk no longer match was changed since, by another
    program or another page, so none of the files is written. Each file goes
    in a temporary file in the same folder first, which then takes its place.
    So a failure leaves the old file whole.

    Parameters
    ----------
    folder : str | Path
        The input folder
    files : list of dict
        Each with `name`, its path from the folder, `text`, and `sha256`, the
        hash of the file as the page last read or saved it, or None for a file
        the folder did not have

    Returns
    -------
    result : dict
        `ok`, and `files`, each file's `name` and the `sha256` of its new
        bytes, for the page's next save. Otherwise `error`, the reason, and
        nothing is written.
    """
    folder = Path(folder).resolve()
    targets = []
    for file in files:
        name, text = file.get("name"), file.get("text")
        if not isinstance(name, str) or not isinstance(text, str):
            return {"ok": False, "error": "The page sent a file with no name or text."}
        target = (folder / name).resolve()
        if _relative(name) is None or not target.is_relative_to(folder):
            return {
                "ok": False,
                "error": f"Cannot save {name}: it is outside the folder.",
            }
        if target.is_dir():
            return {"ok": False, "error": f"Cannot save {name}: it is a folder."}
        loaded = file.get("sha256")
        now = file_hash(target) if target.is_file() else None
        if now != loaded:
            return {
                "ok": False,
                "error": f"{name} changed on disk since this page last read or "
                "saved it, so nothing was saved. Reload the page to see the file as "
                "it is now, or save your work as a download.",
            }
        targets.append((target, text.encode("utf-8")))
    saved = []
    for target, body in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".quicksat_")
        try:
            with os.fdopen(handle, "wb") as out:
                out.write(body)
            if target.is_file():
                shutil.copymode(target, temporary)
            os.replace(temporary, target)
        except OSError:
            Path(temporary).unlink(missing_ok=True)
            raise
        saved.append(
            {
                "name": target.relative_to(folder).as_posix(),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    return {"ok": True, "files": saved}


class EditorServer(ThreadingHTTPServer):
    """
    An editor for one folder, served on this computer, with its runs: the
    Scenario Editor for a folder with a scenario file, and the Sizing Editor for
    a folder of sizing files.

    Parameters
    ----------
    folder : str | Path
        The folder that holds the input files: the scenario file, or at least
        one sizing file
    output : str | Path, optional
        The folder to write the viewer in. The Scenario Editor needs it, and the
        Sizing Editor does not use it.
    port : int, optional
        The port to listen on, and 0 for any free one. By default, `PORT` or the
        next free one after it.
    scenario_file, power_file, consumption_file : str, optional
        The files' names, if not the usual ones. See `editor_data`.
    idle_s : float, optional
        The time with no request from a page after which the server stops by
        itself, in seconds: `IDLE_S` by default
    """

    daemon_threads = True
    # on Windows, this would let a second server take a port that one already has
    allow_reuse_address = sys.platform != "win32"

    def __init__(
        self,
        folder: str | Path,
        output: str | Path | None = None,
        port: int | None = None,
        scenario_file: str = SCENARIO_FILE,
        power_file: str = POWER_FILE,
        consumption_file: str = CONSUMPTION_FILE,
        idle_s: float = IDLE_S,
    ):
        self.folder = Path(folder)
        self.names = (scenario_file, power_file, consumption_file)
        # the Sizing Editor, for a folder of sizing files with no scenario file
        self.sizing = not (self.folder / scenario_file).is_file()
        if self.sizing and not any(
            (self.folder / name).is_file() for name in SIZING_NAMES.values()
        ):
            raise FileNotFoundError(
                f"no scenario file and no sizing file, such as mission.yaml: {self.folder}"
            )
        if not self.sizing and output is None:
            raise ValueError(
                "The Scenario Editor needs an output folder for the viewer."
            )
        self.output = Path(output) if output is not None else None
        # 12 characters, 72 bits: a guess costs a request to this computer
        self.key = secrets.token_urlsafe(9)
        self.run_lock = threading.Lock()
        self.save_lock = threading.Lock()
        # the Sizing Editor's budgets, worked out one request at a time
        self.budgets_lock = threading.Lock()
        # the Activity Designer's last run, as the page its frame shows
        self.design_page: str | None = None
        self.idle_s = idle_s
        # when a page last asked anything, on a clock that the system time does not move
        self.last_request = time.monotonic()
        self.stopping = False
        ports = [port] if port is not None else [*range(PORT, PORT + PORTS_TRIED), 0]
        for number in ports:
            try:
                super().__init__((HOST, number), _Handler)
                break
            except OSError:
                if number == ports[-1]:
                    raise

    def stop(self, why: str) -> None:
        """
        Stop serving, so that `serve` ends. Call it from any thread but the one
        that serves.

        Parameters
        ----------
        why : str
            Why the server stops, for its window
        """
        if self.stopping:
            return
        self.stopping = True
        print(f"{time.strftime('%H:%M:%S')}  stopping, {why}", flush=True)
        # in a thread of its own: `shutdown` waits for `serve_forever` to end
        threading.Thread(target=self.shutdown, daemon=True).start()

    def service_actions(self) -> None:
        """
        Stop, once no page has asked anything for `idle_s`. `serve_forever` calls
        this about twice a second.
        """
        super().service_actions()
        busy = self.run_lock.locked() or self.save_lock.locked()
        if not busy and time.monotonic() - self.last_request > self.idle_s:
            self.stop(f"as no editor page has been open for {self.idle_s / 3600:g} h")

    @property
    def url(self) -> str:
        """The editor's address, with the key. Only this computer can open it."""
        return f"http://localhost:{self.server_port}{PREFIX}editor?key={self.key}"

    def viewer_pages(self) -> list[str]:
        """The viewer pages in the output folder now."""
        if self.output is None:
            return []
        return [
            name
            for name in (SCENARIO_PAGE, POWER_PAGE)
            if (self.output / name).is_file()
        ]

    def page(self) -> str:
        """
        The editor's page, written from the folder as it is now.

        The page holds the SHA-256 of each file it was written from, so that a
        save can tell whether the file changed on disk since.
        """
        if self.sizing:
            data = sizing_data(self.folder)
            data["server"] = {
                "base": PREFIX,
                "key": self.key,
                "folder": _label(self.folder),
                "command": f"python -m quicksat.editor serve {_argument(self.folder)}",
                "viewers": [],
                "idle_h": self.idle_s / 3600,
            }
            return sizing_page(data)
        assert self.output is not None
        data = editor_data(self.folder, *self.names)
        hashes = {
            name: file_hash(self.folder / name)
            for name in self.names
            if (self.folder / name).is_file()
        }
        data["server"] = {
            "base": PREFIX,
            "key": self.key,
            "folder": _label(self.folder),
            "output": _label(self.output),
            # the paths as the user gave them: this page stays on this computer
            "command": f"python -m quicksat.editor serve {_argument(self.folder)} "
            f"{_argument(self.output)}",
            "viewers": self.viewer_pages(),
            "sha256": hashes,
            "idle_h": self.idle_s / 3600,
        }
        return editor_page(data)


_STRANGER = """<!doctype html><meta charset="utf-8"><title>quicksat</title>
<p>This is the quicksat editor's server. Open the address that the server printed
when it started. It ends with a key, <code>?key=</code>, that this address lacks.</p>"""

_NO_DESIGN = """<!doctype html><meta charset="utf-8"><title>quicksat</title>
<body style="background:#08111f;color:#c9d6e8;font:14px sans-serif">
<p>Press <b>Generate scenario</b> to see the run here.</p>"""
"""The Activity Designer's frame before its first run."""

_REQUESTS = {
    "run": "a run",
    "design": "a run of the Activity Designer",
    "save": "a save",
    "budgets": "a work-out of the budgets",
    "stop": "a stop",
}
"""What each address of a POST request takes, for the message that refuses one."""

_SCENARIO_REQUESTS = ("run", "design", "save", "stop")
"""The POST requests that the Scenario Editor's server answers."""

_SIZING_REQUESTS = ("budgets", "stop")
"""The POST requests that the Sizing Editor's server answers."""


class _Handler(BaseHTTPRequestHandler):
    """
    Answers the page: the editor, its status, its runs, the Activity Designer's
    runs and saves, the viewer's files, and the stop.
    """

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
        """
        The address after `PREFIX`, or None if the key is wrong or missing. A
        request with the key keeps the server from stopping by itself.
        """
        address = urlsplit(self.path)
        path = unquote(address.path)
        key = parse_qs(address.query).get("key", [""])[0]
        if not path.startswith(PREFIX) or not secrets.compare_digest(
            key, self.server.key
        ):
            return None
        self.server.last_request = time.monotonic()
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
        elif route == "designer":
            page = self.server.design_page or _NO_DESIGN
            self._send(HTTPStatus.OK, page.encode("utf-8"), "text/html; charset=utf-8")
        elif route.startswith("viewer/"):
            self._viewer_file(route.removeprefix("viewer/"))
        else:
            self._send(HTTPStatus.NOT_FOUND, b"Not found.", "text/plain")

    def _viewer_file(self, name: str) -> None:
        """A file of the output folder: a page, a script or an attitude file."""
        output = self.server.output
        kind = VIEWER_TYPES.get(Path(name).suffix)
        if (
            output is None
            or "/" in name
            or "\\" in name
            or name.startswith(".")
            or not kind
            or not (output / name).is_file()
        ):
            self._send(HTTPStatus.NOT_FOUND, b"Not found.", "text/plain")
            return
        path = output / name
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
        """A run, a run of the Activity Designer, a save of the page's files, or a stop."""
        if not self._own("Host") or (
            "Origin" in self.headers and not self._own("Origin", "http://")
        ):
            self._send(HTTPStatus.FORBIDDEN, b"Not this server's page.", "text/plain")
            return
        route = self._route()
        allowed = _SIZING_REQUESTS if self.server.sizing else _SCENARIO_REQUESTS
        if route is None or route not in allowed:
            self._send(HTTPStatus.NOT_FOUND, b"Not found.", "text/plain")
            return
        refused = {"ok": False, "error": f"The request is not {_REQUESTS[route]}."}
        length = int(self.headers.get("Content-Length") or 0)
        if (
            not self.headers.get("Content-Type", "").startswith("application/json")
            or length > MAX_BODY
        ):
            self._json(HTTPStatus.BAD_REQUEST, {**refused, "checks": []})
            return
        if route == "stop":
            self._stop()
            return
        try:
            request = json.loads(self.rfile.read(length))
            files = request["files"]
            if not isinstance(files, list):
                raise TypeError("files is not a list")
        except (ValueError, KeyError, TypeError):
            self._json(HTTPStatus.BAD_REQUEST, {**refused, "checks": []})
            return
        if route == "save":
            self._save(files)
        elif route == "budgets":
            self._budgets(files)
        else:
            self._run(route, files, bool(request.get("repeat", False)))

    def _run(self, route: str, files: list, repeat: bool) -> None:
        """A run of the page's files: the viewer, or the Activity Designer's run."""
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
        design = route == "design"
        try:
            doing = "generating the scenario" if design else "running the page's files"
            print(f"{time.strftime('%H:%M:%S')}  {doing} ...", flush=True)
            if design:
                result = design_files(files, repeat)
                if result["ok"]:
                    self.server.design_page = designer_page(result.pop("data"))
            else:
                assert self.server.output is not None
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
        now = time.strftime("%H:%M:%S")
        if not result["ok"]:
            missing = "no scenario" if design else "no viewer"
            print(f"{now}  {missing}: {result['error']}", flush=True)
        elif design:
            print(f"{now}  generated in {result['seconds']} s", flush=True)
        else:
            print(
                f"{now}  wrote {self.server.output / result['page']} in {result['seconds']} s",
                flush=True,
            )
        self._json(HTTPStatus.OK, result)

    def _budgets(self, files: list) -> None:
        """A work-out of the sizing budgets from the page's files, one at a time."""
        with self.server.budgets_lock:
            try:
                result = budget_files(files)
            except Exception as error:  # a fault in quicksat: show it, and keep serving
                traceback.print_exc()
                result = {
                    "ok": False,
                    "error": f"quicksat failed: {type(error).__name__}: {error}. The server's window shows the details.",
                }
        if not result["ok"]:
            print(
                f"{time.strftime('%H:%M:%S')}  no budgets: {result['error']}",
                flush=True,
            )
        self._json(HTTPStatus.OK, result)

    def _save(self, files: list) -> None:
        """A save of the page's files into the input folder."""
        with self.server.save_lock:
            try:
                result = save_files(self.server.folder, files)
            except OSError as error:
                result = {"ok": False, "error": f"Cannot save: {error}"}
        now = time.strftime("%H:%M:%S")
        if result["ok"]:
            names = ", ".join(file["name"] for file in result["files"])
            print(f"{now}  saved {names} in {_label(self.server.folder)}", flush=True)
        else:
            print(f"{now}  nothing saved: {result['error']}", flush=True)
        self._json(HTTPStatus.OK, result)

    def _stop(self) -> None:
        """Stop the server, unless a run or a save is going on."""
        server = self.server
        if not server.run_lock.acquire(blocking=False):
            busy = "A run is going. Wait for it to end, then stop the server."
        elif not server.save_lock.acquire(blocking=False):
            server.run_lock.release()
            busy = "A save is going. Wait for it to end, then stop the server."
        else:
            busy = ""
        if busy:
            self._json(HTTPStatus.CONFLICT, {"ok": False, "error": busy})
            return
        # the locks stay taken, so that no run or save starts before the server stops
        self._json(HTTPStatus.OK, {"ok": True})
        server.stop("as the page asked")


def serve(server: EditorServer, open_browser: bool = True) -> None:
    """
    Serve the editor until the user stops it, on the page or with Ctrl+C.

    Parameters
    ----------
    server : EditorServer
        The server, made and listening
    open_browser : bool, optional
        Whether to open the editor in the browser
    """
    editor = "Sizing Editor" if server.sizing else "Scenario Editor"
    print(f"The {editor} for {_label(server.folder)} is at\n\n    {server.url}\n")
    if server.output is None:
        print("The page's Budgets tab works out the budgets as you edit.")
    else:
        print(f"Create the viewer on the page, and it goes in {_label(server.output)}.")
    print(
        "Keep this window open while you work. To stop the server, click Stop "
        "the server on the page, or press Ctrl+C. It stops by itself after "
        f"{server.idle_s / 3600:g} h with no editor page open.",
        flush=True,
    )
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()  # a new line, after the ^C that the terminal shows
    finally:
        server.server_close()
    print("The server has stopped.")
