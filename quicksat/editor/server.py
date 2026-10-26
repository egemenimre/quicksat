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

**Compute**, on the Scenario Editor's Thermal tab, sends the files in the same
way. `thermal_files` works out the payload's heat account, and writes nothing.
The server keeps the run and each surface's absorbed heat, with a hash of what
they depend on: the scenario and its files, the self-shadowing and the
surfaces. A change to the heaters, the flows or the dissipation then reuses
them, and only the sums are done again.

The work of each of these requests is in `quicksat.editor.actions`. This module
answers the requests.

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

import json
import secrets
import sys
import threading
import time
import traceback
import webbrowser
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from quicksat.editor.actions import (
    budget_files,
    design_files,
    file_hash,
    run_files,
    save_files,
    thermal_files,
)
from quicksat.editor.scenario import editor_data, editor_page
from quicksat.editor.sizing import NAMES as SIZING_NAMES
from quicksat.editor.sizing import sizing_data, sizing_page
from quicksat.power import CONSUMPTION_FILES, POWER_FILE
from quicksat.power.viewer import PAGE_FILE as POWER_PAGE
from quicksat.scenario import SCENARIO_FILE
from quicksat.scenario.viewer import PAGE_FILE as SCENARIO_PAGE
from quicksat.scenario.viewer import designer_page
from quicksat.thermal import THERMAL_FILE

HOST = "127.0.0.1"
"""The address the server listens on: this computer only."""

PORT = 8780
"""The port the server tries first. If another program has it, the server tries
the next ones, then any free port."""

PORTS_TRIED = 20
"""How many ports from `PORT` on the server tries, before any free one."""

PREFIX = "/quicksat/"
"""The start of every address the server answers: `editor`, `status`, `run`,
`design`, `designer`, `save`, `budgets`, `thermal`, `stop` and `viewer/` follow
it."""

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


def _label(path: Path) -> str:
    """A folder as the user gave it when relative, and its name otherwise."""
    return path.as_posix() if not path.is_absolute() else path.name


def _argument(path: Path) -> str:
    """A path as a command line takes it: in double quotes if it has a space."""
    return f'"{path}"' if " " in str(path) else str(path)


def _log(text: str) -> None:
    """Print a line in the server's window, after the time of day."""
    print(f"{time.strftime('%H:%M:%S')}  {text}", flush=True)


def _guarded(work: Callable[[], dict], **fields) -> dict:
    """
    The result of a request's work, with a fault in quicksat as an error, so that
    the server keeps serving.

    Parameters
    ----------
    work : callable
        Does the work, and gives the result
    **fields
        The fields that an error result also needs, such as `checks`

    Returns
    -------
    result : dict
        The work's result. After a fault, `ok` is false and `error` names the
        fault, and the traceback goes to the server's window.
    """
    try:
        return work()
    except Exception as error:  # a fault in quicksat: show it, and keep serving
        traceback.print_exc()
        return {
            "ok": False,
            "error": f"quicksat failed: {type(error).__name__}: {error}. The "
            "server's window shows the details.",
            **fields,
        }


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
    scenario_file, power_file, consumption_files, thermal_file : optional
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
        consumption_files: dict[str, str] = CONSUMPTION_FILES,
        idle_s: float = IDLE_S,
        thermal_file: str = THERMAL_FILE,
    ):
        self.folder = Path(folder)
        self.names = (scenario_file, power_file, consumption_files, thermal_file)
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
        # the Thermal tab's heat account, one request at a time, with the run
        # and the surfaces' heat it keeps
        self.thermal_lock = threading.Lock()
        self.thermal_cache: dict = {}
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
        _log(f"stopping, {why}")
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
        scenario_file, power_file, consumption_files, thermal_file = self.names
        hashes = {
            name: file_hash(self.folder / name)
            for name in (
                scenario_file,
                power_file,
                *consumption_files.values(),
                thermal_file,
            )
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
    "thermal": "a work-out of the heat account",
    "stop": "a stop",
}
"""What each address of a POST request takes, for the message that refuses one."""

_SCENARIO_REQUESTS = ("run", "design", "save", "thermal", "stop")
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
        elif route == "thermal":
            self._thermal(files)
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
        output = self.server.output

        def work() -> dict:
            if not design:
                assert output is not None
                return run_files(files, output)
            result = design_files(files, repeat)
            if result["ok"]:
                self.server.design_page = designer_page(result.pop("data"))
            return result

        try:
            _log(
                "generating the scenario ..."
                if design
                else "running the page's files ..."
            )
            result = _guarded(work, checks=[])
        finally:
            self.server.run_lock.release()
        if not result["ok"]:
            _log(f"{'no scenario' if design else 'no viewer'}: {result['error']}")
        elif design:
            _log(f"generated in {result['seconds']} s")
        else:
            assert output is not None
            _log(f"wrote {output / result['page']} in {result['seconds']} s")
        self._json(HTTPStatus.OK, result)

    def _budgets(self, files: list) -> None:
        """A work-out of the sizing budgets from the page's files, one at a time."""
        with self.server.budgets_lock:
            result = _guarded(lambda: budget_files(files))
        if not result["ok"]:
            _log(f"no budgets: {result['error']}")
        self._json(HTTPStatus.OK, result)

    def _thermal(self, files: list) -> None:
        """A work-out of the heat account from the page's files, one at a time."""
        with self.server.thermal_lock:
            result = _guarded(
                lambda: thermal_files(files, self.server.thermal_cache), checks=[]
            )
        if not result["ok"]:
            _log(f"no heat account: {result['error']}")
        else:
            how = "from the kept run" if result["reused"] else "with a new run"
            _log(f"computed the heat account {how} in {result['seconds']} s")
        self._json(HTTPStatus.OK, result)

    def _save(self, files: list) -> None:
        """A save of the page's files into the input folder."""
        with self.server.save_lock:
            try:
                result = save_files(self.server.folder, files)
            except OSError as error:
                result = {"ok": False, "error": f"Cannot save: {error}"}
        if result["ok"]:
            names = ", ".join(file["name"] for file in result["files"])
            _log(f"saved {names} in {_label(self.server.folder)}")
        else:
            _log(f"nothing saved: {result['error']}")
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
